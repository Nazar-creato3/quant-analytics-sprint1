"""Free macro panel: FRED + Eurostat + CFTC, joined on knowledge_time."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.services.pit.clock import Observation, as_day, latest_visible, observation

# What we actually run. Fetchers live in fred_bulk_store / public_alt; this is the PIT join.
FRED_PANEL: tuple[tuple[str, str], ...] = (
    ("VIXCLS", "vol"),
    ("DGS2", "curve"),
    ("DGS10", "curve"),
    ("DGS30", "curve"),
    ("T10Y2Y", "curve"),
    ("DFII10", "real_rate"),
    ("T10YIE", "real_rate"),
    ("FEDFUNDS", "policy"),
    ("UNRATE", "labor"),
    ("PAYEMS", "labor"),
    ("JTSJOL", "labor"),
    ("CPIAUCSL", "prices"),
    ("PPIFIS", "prices"),
    ("BAMLH0A0HYM2", "credit"),
    ("DTWEXBGS", "fx"),
    ("DCOILBRENTEU", "commodity"),
)

EUROSTAT_PANEL: tuple[tuple[str, str], ...] = (
    ("ESI", "survey"),
    ("HICP", "prices"),
    ("GDP", "activity"),
)

CFTC_PANEL: tuple[str, ...] = ("ES", "GC", "CL", "DX")


def observations_from_fred_payload(series_id: str, payload: Mapping[str, Any] | None) -> list[Observation]:
    """FRED vintage: realtime_start if present, else lag table on observation date."""
    if not payload:
        return []
    rows = payload.get("observations") or []
    out: list[Observation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("value")
        if raw in {None, "", "."}:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        released = row.get("realtime_start") or row.get("realtimeStart")
        out.append(
            observation(
                series_id,
                val,
                event_time=row.get("date"),
                released=released,
            )
        )
    return out


def panel_as_of(
    series_payloads: Mapping[str, Mapping[str, Any] | None],
    as_of: Any,
    *,
    extra: Mapping[str, list[Observation]] | None = None,
) -> dict[str, float]:
    """One value per series, only if knowledge_time ≤ as_of."""
    day = as_day(as_of)
    out: dict[str, float] = {}
    for sid, payload in series_payloads.items():
        last = latest_visible(observations_from_fred_payload(sid, payload), day)
        if last is not None:
            out[sid] = last.value
    for sid, rows in (extra or {}).items():
        last = latest_visible(list(rows), day)
        if last is not None:
            out[sid] = last.value
    return out


def eurostat_observation(series_id: str, period: Any, value: float, *, released: Any = None) -> Observation:
    return observation(series_id, value, event_time=period, released=released)


def cftc_observation(contract: str, report_date: Any, lev_net_share: float, *, released: Any = None) -> Observation:
    sid = f"CFTC_{str(contract).upper()}"
    return observation(sid, lev_net_share, event_time=report_date, released=released)
