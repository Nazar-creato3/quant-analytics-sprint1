"""Conviction- and liquidity-aware risk budget per maneuver (not uniform portfolio/N)."""
from __future__ import annotations

import math

from app.core.logging import get_logger

logger = get_logger(__name__)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


_KELLY_TTL_SEC = 3600.0
_kelly_cache: tuple[float, float | None] | None = None


def _quarter_kelly_cap_pct() -> float | None:
    """Optional quarter-Kelly cap from public track record (spec A.4).

    The track record is a replay over reference series (~40 s of CPU) and does not depend on
    the ticker being sized: compute it once per hour, not once per ticker.
    """
    global _kelly_cache
    import time

    now = time.monotonic()
    if _kelly_cache is not None and now - _kelly_cache[0] < _KELLY_TTL_SEC:
        return _kelly_cache[1]
    found, value = _read_kelly_file()
    if not found:
        value = _compute_quarter_kelly_cap_pct()
        _write_kelly_file(value)
    _kelly_cache = (now, value)
    return value


def _kelly_file():
    from pathlib import Path

    from app.services.price_history import store

    try:
        base = Path(store.root()).parent
    except Exception:
        import tempfile

        base = Path(tempfile.gettempdir())
    return base / "cache" / "kelly_cap.json"


def _read_kelly_file() -> tuple[bool, float | None]:
    """Shared across worker processes and restarts: the replay is computed once per hour per server."""
    import json
    import time

    try:
        raw = json.loads(_kelly_file().read_text())
        if time.time() - float(raw["ts"]) < _KELLY_TTL_SEC:
            v = raw.get("value")
            return True, (float(v) if v is not None else None)
    except Exception:
        pass
    return False, None


def _write_kelly_file(value: float | None) -> None:
    import json
    import time

    try:
        path = _kelly_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ts": time.time(), "value": value}))
        tmp.replace(path)
    except Exception as exc:
        logger.debug("Kelly cache write skipped", error=str(exc))


def _compute_quarter_kelly_cap_pct() -> float | None:
    try:
        from app.services.track_record.service import TrackRecordService
        from app.utils.helpers import kelly_fraction

        tr = TrackRecordService().get_public_summary().to_dict()
        agg = (tr or {}).get("aggregate") or {}
        win_rate = agg.get("win_rate")
        avg_win = agg.get("avg_win_pct") or agg.get("avg_win")
        avg_loss = agg.get("avg_loss_pct") or agg.get("avg_loss")
        if win_rate is None or avg_win is None or avg_loss is None:
            return None
        kelly = kelly_fraction(float(win_rate), float(avg_win), float(avg_loss))
        return round(kelly * 100, 4) if kelly > 0 else None
    except Exception as exc:
        logger.debug("Kelly cap skipped", error=str(exc))
        return None


def volume_zscore(recent_volumes: list[float]) -> float:
    """Simple z-score of last bar vs trailing mean (liquidity proxy)."""
    if len(recent_volumes) < 5:
        return 0.0
    tail = recent_volumes[-20:]
    mean = sum(tail) / len(tail)
    if mean <= 0:
        return 0.0
    var = sum((v - mean) ** 2 for v in tail) / len(tail)
    std = math.sqrt(var) if var > 0 else mean
    if std <= 0:
        return 0.0
    return _clamp((tail[-1] - mean) / std, -2.0, 2.0)


def conviction_risk_pct(
    *,
    base_max_risk_pct: float,
    confidence: float,
    atr_pct: float,
    volume_z: float = 0.0,
) -> float:
    """
    Derive per-trade risk % from conviction, vol, and liquidity.

    Produces a spread of notionals (typically well below the per-position notional cap)
    instead of every idea sizing to the same portfolio fraction.
    """
    conf = _clamp(confidence, 0.0, 1.0)
    conf_factor = 0.40 + 0.60 * conf
    safe_atr = max(atr_pct, 0.003)
    vol_factor = _clamp(0.018 / safe_atr, 0.45, 1.25)
    liq_factor = _clamp(0.90 + volume_z * 0.08, 0.55, 1.20)
    scaled = base_max_risk_pct * conf_factor * vol_factor * liq_factor
    floor = max(0.12, base_max_risk_pct * 0.25)
    capped = _clamp(scaled, floor, base_max_risk_pct)
    kelly_cap = _quarter_kelly_cap_pct()
    if kelly_cap is not None:
        capped = min(capped, kelly_cap)
    return round(capped, 4)
