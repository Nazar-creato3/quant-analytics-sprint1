"""Daily point-in-time snapshots of free extras. No vendor C calls."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_FUND_KEYS = (
    "fmp_pe_inv",
    "fmp_roe",
    "fmp_roa",
    "fmp_de",
    "fmp_cr",
    "fmp_margin",
    "fmp_beta",
    "fmp_div",
    "fmp_log_mcap",
    "fund_present",
    "style_quality",
    "style_value",
    "style_leverage",
    "style_present",
)


def _pit_dir() -> Path:
    raw = getattr(settings, "PIT_STORE_DIR", "") or ""
    return Path(raw) if raw.strip() else Path("/app/data/pit_snapshots")


def load_pit_day(symbol: str, as_of: str) -> dict[str, float]:
    path = _pit_dir() / symbol.strip().upper() / f"{str(as_of)[:10]}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    feats = raw.get("features") or {}
    out: dict[str, float] = {}
    for k, v in feats.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def persist_pit_snapshot(symbol: str, extras: Mapping[str, float]) -> Path | None:
    """Write today's extras. Overwrites same-day file; history is the dated name."""
    features = {k: float(extras[k]) for k in _FUND_KEYS if k in extras}
    if not features:
        return None
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = _pit_dir() / symbol.upper()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{day}.json"
        path.write_text(
            json.dumps(
                {
                    "symbol": symbol.upper(),
                    "event_time": day,
                    "knowledge_time": day,
                    "as_of": day,
                    "pit": True,
                    "features": features,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path
    except OSError as exc:
        logger.debug("pit snapshot skip", symbol=symbol, error=str(exc)[:120])
        return None
