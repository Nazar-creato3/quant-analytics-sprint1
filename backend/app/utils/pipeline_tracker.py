"""
Pipeline run tracking.

L1 in-memory cache plus Redis persistence (shared across uvicorn workers and Celery).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

import redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}

_REDIS_KEY_PREFIX = "pipeline:run:"
_PIPELINE_RUN_TTL_SECONDS = 48 * 3600

_redis_client: redis.Redis | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redis_key(run_id: str) -> str:
    return f"{_REDIS_KEY_PREFIX}{run_id}"


def _get_redis() -> redis.Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        _redis_client.ping()
        return _redis_client
    except Exception as exc:
        logger.warning("Pipeline tracker Redis unavailable", error=str(exc))
        _redis_client = None
        return None


def _redis_get(run_id: str) -> dict[str, Any] | None:
    client = _get_redis()
    if client is None:
        return None
    try:
        raw = client.get(_redis_key(run_id))
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("Pipeline tracker Redis GET failed", run_id=run_id, error=str(exc))
        return None


def _redis_set(run_id: str, record: dict[str, Any]) -> None:
    client = _get_redis()
    if client is None:
        return
    try:
        client.setex(
            _redis_key(run_id),
            _PIPELINE_RUN_TTL_SECONDS,
            json.dumps(record, default=str),
        )
    except Exception as exc:
        logger.warning("Pipeline tracker Redis SET failed", run_id=run_id, error=str(exc))


def _persist(record: dict[str, Any]) -> None:
    run_id = record.get("run_id")
    if not run_id:
        return
    with _lock:
        _runs[str(run_id)] = dict(record)
    _redis_set(str(run_id), record)


def _load(run_id: str) -> dict[str, Any] | None:
    with _lock:
        record = _runs.get(run_id)
        if record is not None:
            return dict(record)
    remote = _redis_get(run_id)
    if remote is not None:
        with _lock:
            _runs[run_id] = dict(remote)
        return dict(remote)
    return None


def reset_store() -> None:
    """Clear in-memory runs. For tests only."""
    with _lock:
        _runs.clear()


def reset_redis_client() -> None:
    """Drop cached Redis client. For tests only."""
    global _redis_client
    _redis_client = None


def track_run(
    run_id: str,
    task_id: str,
    triggered_by: str = "manual",
    status: str = "queued",
    error: str | None = None,
    report_id: str | None = None,
) -> None:
    """Register a new pipeline run."""
    now = _utc_now()
    record = {
        "run_id": run_id,
        "task_id": task_id,
        "triggered_by": triggered_by,
        "status": status,
        "error": error,
        "report_id": report_id,
        "created_at": now,
        "updated_at": now,
    }
    _persist(record)


def mark_complete(run_id: str, report_id: str) -> None:
    """Mark a run as successfully completed."""
    _patch(run_id, status="complete", report_id=report_id, error=None)


def mark_failed(run_id: str, error: str) -> None:
    """Mark a run as failed."""
    _patch(run_id, status="failed", error=error)


def get_run(run_id: str) -> dict[str, Any] | None:
    """Return run metadata compatible with PipelineRunResponse fields, or None."""
    return _load(run_id)


def _patch(run_id: str, **fields: Any) -> None:
    record = _load(run_id)
    if record is None:
        now = _utc_now()
        record = {
            "run_id": run_id,
            "task_id": "",
            "triggered_by": "",
            "status": "queued",
            "error": None,
            "report_id": None,
            "created_at": now,
            "updated_at": now,
        }
    record.update(fields)
    record["updated_at"] = _utc_now()
    _persist(record)
