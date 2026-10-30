"""Daily PIT session store: one frozen book per trading day for replay."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from app.core.config import settings
from app.core.logging import get_logger
from app.services.pit.clock import as_day, reject_future_as_of, utc_today

logger = get_logger(__name__)


def _root() -> Path:
    raw = getattr(settings, "PIT_STORE_DIR", "") or ""
    base = Path(raw) if str(raw).strip() else Path("/app/data/pit_snapshots")
    return base / "_sessions"


def session_path(as_of: str) -> Path:
    return _root() / f"{as_day(as_of)}.json"


def build_session(
    *,
    as_of: str,
    knowledge_time: str | None = None,
    universe: list[str] | None = None,
    macro: Mapping[str, Any] | None = None,
    cross_asset: Mapping[str, Any] | None = None,
    extras_by_symbol: Mapping[str, Mapping[str, float]] | None = None,
    news_events: list[Mapping[str, Any]] | None = None,
    short_interest: Mapping[str, Mapping[str, float]] | None = None,
    slippage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    day = as_day(as_of) or utc_today()
    known = as_day(knowledge_time) or day
    return {
        "event_time": day,
        "knowledge_time": known,
        "pit": True,
        "universe": [str(s).upper() for s in (universe or [])],
        "macro": dict(macro or {}),
        "cross_asset": dict(cross_asset or {}),
        "extras_by_symbol": {str(k).upper(): dict(v) for k, v in (extras_by_symbol or {}).items()},
        "news_events": list(news_events or []),
        "short_interest": {str(k).upper(): dict(v) for k, v in (short_interest or {}).items()},
        "slippage": dict(slippage or {}),
    }


def persist_session(payload: Mapping[str, Any]) -> Path | None:
    day = as_day(payload.get("event_time") or payload.get("as_of"))
    if not day:
        return None
    folder = _root()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = session_path(day)
        body = dict(payload)
        body["event_time"] = day
        body.setdefault("knowledge_time", day)
        path.write_text(json.dumps(body, ensure_ascii=False, default=str), encoding="utf-8")
        return path
    except OSError as exc:
        logger.debug("pit session skip", day=day, error=str(exc)[:120])
        return None


def load_session(as_of: str, *, today: str | None = None) -> dict[str, Any] | None:
    day = reject_future_as_of(as_of, today=today)
    if not day:
        return None
    path = session_path(day)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def replay_sessions(*, through: str | None = None, today: str | None = None) -> list[dict[str, Any]]:
    """Oldest → newest sessions with knowledge_time ≤ through (default today)."""
    cap = reject_future_as_of(through or utc_today(), today=today) or utc_today()
    folder = _root()
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("????-??-??.json")):
        day = path.stem
        if day > cap:
            continue
        row = load_session(day, today=today or cap)
        if row:
            known = as_day(row.get("knowledge_time") or day)
            if known and known <= cap:
                out.append(row)
    return out
