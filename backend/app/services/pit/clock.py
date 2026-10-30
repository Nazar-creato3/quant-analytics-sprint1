"""Point-in-time clock: event_time is when the world moved; knowledge_time is when it was knowable."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


class LookAheadError(ValueError):
    """A row was requested as-of a time before it could have been known."""


def as_day(value: Any) -> str:
    """Calendar day UTC YYYY-MM-DD. Empty / unparsable → ''."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return ""


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def add_days(day: str, n: int) -> str:
    d = as_day(day)
    if not d:
        return ""
    base = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (base + timedelta(days=int(n))).strftime("%Y-%m-%d")


# Conservative publication lags (calendar days after event_time) when vintage is missing.
# Prefer an explicit `filed` / `released` / `realtime_start` over these defaults.
VINTAGE_LAG_DAYS: dict[str, int] = {
    "VIXCLS": 0,
    "DGS10": 0,
    "DGS2": 0,
    "DGS30": 0,
    "DFII10": 0,
    "T10YIE": 0,
    "T10Y2Y": 0,
    "FEDFUNDS": 0,
    "DTWEXBGS": 0,
    "DCOILBRENTEU": 0,
    "BAMLH0A0HYM2": 0,
    "UNRATE": 12,
    "PAYEMS": 12,
    "CPIAUCSL": 14,
    "PPIFIS": 14,
    "JTSJOL": 20,
    "ESI": 5,
    "HICP": 18,
    "GDP": 35,
    "CFTC_COT": 4,
    "FINRA_SI": 8,
    "EDGAR_10K": 0,
    "FMP_FUND": 1,
    "NEWS": 0,
}


def infer_knowledge_time(
    event_time: Any,
    *,
    series_id: str,
    released: Any = None,
) -> str:
    """knowledge_time ≥ event_time. Released/filed wins over lag table."""
    event = as_day(event_time)
    known = as_day(released)
    if known and event:
        return known if known >= event else event
    if known:
        return known
    if not event:
        return ""
    lag = int(VINTAGE_LAG_DAYS.get(str(series_id).upper(), VINTAGE_LAG_DAYS.get(series_id, 1)))
    return add_days(event, max(0, lag))


@dataclass(frozen=True, slots=True)
class Observation:
    series_id: str
    event_time: str
    knowledge_time: str
    value: float

    def known_at(self, as_of: Any) -> bool:
        as_of_day = as_day(as_of)
        known = as_day(self.knowledge_time)
        if not as_of_day or not known:
            return False
        return known <= as_of_day


def observation(
    series_id: str,
    value: float,
    *,
    event_time: Any,
    released: Any = None,
) -> Observation:
    event = as_day(event_time)
    known = infer_knowledge_time(event, series_id=series_id, released=released)
    return Observation(
        series_id=str(series_id),
        event_time=event,
        knowledge_time=known,
        value=float(value),
    )


def visible_as_of(rows: list[Observation], as_of: Any) -> list[Observation]:
    """Drop anything not yet released. Never substitutes a later vintage."""
    day = as_day(as_of)
    return [row for row in rows if row.known_at(day)]


def latest_visible(rows: list[Observation], as_of: Any) -> Observation | None:
    known = visible_as_of(rows, as_of)
    if not known:
        return None
    known.sort(key=lambda r: (r.knowledge_time, r.event_time))
    return known[-1]


def reject_future_as_of(as_of: Any, *, today: str | None = None) -> str:
    """Backtests may not query a day after UTC today."""
    day = as_day(as_of)
    cap = today or utc_today()
    if not day or day > cap:
        return ""
    return day
