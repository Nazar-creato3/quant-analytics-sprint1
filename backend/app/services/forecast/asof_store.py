"""Dated feature rows on disk. Train still works if a day is missing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _root() -> Path:
    raw = getattr(settings, "PIT_STORE_DIR", "") or ""
    base = Path(raw) if raw.strip() else Path("/app/data/pit_snapshots")
    return base / "_asof"


def persist_asof(symbol: str, features: Mapping[str, Any], *, as_of: str | None = None) -> Path | None:
    day = as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = _root() / symbol.strip().upper()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{day}.json"
        slim = {k: float(v) for k, v in features.items() if _is_num(v)}
        path.write_text(
            json.dumps({"symbol": symbol.upper(), "as_of": day, "features": slim}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path
    except OSError as exc:
        logger.debug("asof persist skip", symbol=symbol, error=str(exc)[:120])
        return None


def extras_as_of(symbol: str, as_of: str | None) -> dict[str, float]:
    """PIT extras for that calendar day only. Missing day → {}. Never today's file on an old bar."""
    if not symbol or not as_of:
        return {}
    day = str(as_of).strip()[:10]
    if len(day) < 10:
        return {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    from app.services.pit.clock import reject_future_as_of

    if not reject_future_as_of(day, today=today):
        return {}
    merged = dict(load_asof(symbol, day))
    try:
        from app.services.forecast.pit_snapshots import load_pit_day

        pit = load_pit_day(symbol, day)
        for k, v in pit.items():
            if k not in merged:
                merged[k] = v
    except Exception:
        pass
    return merged


def load_asof(symbol: str, as_of: str) -> dict[str, float]:
    path = _root() / symbol.strip().upper() / f"{as_of}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    feats = raw.get("features") or {}
    out: dict[str, float] = {}
    for k, v in feats.items():
        if _is_num(v):
            out[str(k)] = float(v)
    return out


def _is_num(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False
