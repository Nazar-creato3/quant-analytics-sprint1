"""Throttle expensive health checks (live LLM / chat) — avoid AITunnel bleed on hourly cron."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.utils.cache import cache_get, cache_set

logger = get_logger(__name__)

_CACHE_PREFIX = "health:expensive:"
_DEFAULT_CACHE_TTL_S = 86400.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_cached_expensive_check(check_name: str) -> dict[str, Any] | None:
    raw = await cache_get(f"{_CACHE_PREFIX}{check_name}")
    if isinstance(raw, dict) and raw.get("row"):
        return raw
    return None


async def store_expensive_check_result(
    check_name: str,
    row: dict[str, Any],
    *,
    ttl_s: float | None = None,
) -> None:
    settings = get_settings()
    ttl = ttl_s or float(getattr(settings, "HEALTH_EXPENSIVE_CACHE_TTL_SECONDS", _DEFAULT_CACHE_TTL_S))
    payload = {
        "row": row,
        "cached_at": _now_iso(),
        "check_name": check_name,
    }
    await cache_set(f"{_CACHE_PREFIX}{check_name}", payload, ttl=int(max(60, ttl)))


def _row_with_cache_meta(row: dict[str, Any], cached: dict[str, Any]) -> dict[str, Any]:
    cached_at = cached.get("cached_at") or "unknown"
    age_note = f"cached live result from {cached_at}"
    detail = row.get("detail")
    if detail:
        row = {**row, "detail": f"{detail}; {age_note}"}
    else:
        row = {**row, "detail": age_note}
    row["cached"] = True
    row["cached_at"] = cached_at
    return row


async def run_throttled_expensive_check(
    check_name: str,
    runner: Any,
    *,
    settings: Settings | None = None,
    enabled_attr: str,
    interval_attr: str,
) -> dict[str, Any]:
    """
    Run `runner(settings)` only when enabled and interval elapsed; otherwise reuse cache.

    When disabled via settings flag, return passed row with skipped=live_disabled (no LLM cost).
    """
    settings = settings or get_settings()
    enabled = bool(getattr(settings, enabled_attr, False))
    interval_s = max(60.0, float(getattr(settings, interval_attr, 10800.0)))

    if not enabled:
        return {
            "name": check_name,
            "status": "passed",
            "error": None,
            "skipped": "live_disabled",
            "mode": "config_off",
            "detail": "живой вызов отключён (HEALTH_*_ENABLED=false) — без расхода AITunnel",
        }

    cached = await get_cached_expensive_check(check_name)
    if cached:
        cached_at = cached.get("cached_at")
        try:
            ts = datetime.fromisoformat(str(cached_at).replace("Z", "+00:00"))
            age_s = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        except Exception:
            age_s = interval_s + 1
        if age_s < interval_s:
            base_row = dict(cached.get("row") or {})
            base_row["name"] = check_name
            return _row_with_cache_meta(base_row, cached)

    started = time.perf_counter()
    row = await runner(settings)
    row = dict(row)
    row["name"] = check_name
    row["live_run_at"] = _now_iso()
    row["live_duration_ms"] = int((time.perf_counter() - started) * 1000)
    await store_expensive_check_result(check_name, row)
    logger.info(
        "health_expensive_check_live",
        check=check_name,
        status=row.get("status"),
        duration_ms=row.get("live_duration_ms"),
    )
    return row
