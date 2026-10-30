"""FINRA short interest → squeeze / crowding features. Settlement ≠ publication."""
from __future__ import annotations

from typing import Any, Mapping

from app.services.pit.clock import Observation, as_day, latest_visible, observation


def _f(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            try:
                return float(row[key])
            except (TypeError, ValueError):
                continue
    return None


def short_observation(row: Mapping[str, Any], *, symbol: str = "") -> Observation | None:
    settle = row.get("settlement_date") or row.get("settlementDate")
    current = _f(row, "current_short_position", "currentShortPositionQuantity")
    if current is None or not as_day(settle):
        return None
    released = row.get("published_at") or row.get("released")
    return observation(
        "FINRA_SI",
        current,
        event_time=settle,
        released=released,
    )


def squeeze_features(history: list[Mapping[str, Any]], *, as_of: Any, symbol: str = "") -> dict[str, float]:
    """Only rows whose publication (or lag) is known by as_of."""
    obs: list[Observation] = []
    dtc_rows: list[tuple[str, float]] = []
    vol_rows: list[tuple[str, float]] = []
    for row in history:
        o = short_observation(row, symbol=symbol)
        if o is None:
            continue
        obs.append(o)
        dtc = _f(row, "days_to_cover", "daysToCoverQuantity")
        if dtc is not None:
            dtc_rows.append((o.knowledge_time, dtc))
        vol = _f(row, "average_daily_volume", "averageDailyVolumeQuantity")
        if vol is not None:
            vol_rows.append((o.knowledge_time, vol))
    last = latest_visible(obs, as_of)
    if last is None:
        return {"si_level": 0.0, "si_chg": 0.0, "days_to_cover": 0.0, "crowding": 0.0, "present": 0.0}
    visible = [o for o in obs if o.known_at(as_of)]
    visible.sort(key=lambda r: r.knowledge_time)
    prev = visible[-2].value if len(visible) >= 2 else last.value
    chg = (last.value - prev) / prev if prev else 0.0
    cap = as_day(as_of)
    dtc = 0.0
    latest_dtc_day = ""
    for known, val in dtc_rows:
        if known <= cap and known >= latest_dtc_day:
            latest_dtc_day = known
            dtc = val
    crowding = 0.0
    if dtc > 0:
        crowding = max(-1.0, min(1.0, (dtc - 2.0) / 8.0))
    if chg > 0:
        crowding = max(-1.0, min(1.0, crowding + 0.25 * max(-1.0, min(1.0, chg))))
    return {
        "si_level": round(last.value, 2),
        "si_chg": round(chg, 6),
        "days_to_cover": round(dtc, 4),
        "crowding": round(crowding, 6),
        "present": 1.0,
    }
