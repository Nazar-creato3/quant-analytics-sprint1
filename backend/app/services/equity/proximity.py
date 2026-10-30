"""Event proximity risk — pure calculation for earnings/dividend windows."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class ProximityEventType(str, Enum):
    NONE = "none"
    EARNINGS = "earnings"
    DIVIDEND = "dividend"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class EventProximityResult:
    """Outcome of event_proximity_risk calculation."""

    is_at_risk: bool
    event_type: ProximityEventType
    days_to_nearest_event: float | None
    nearest_event_at: datetime | None
    earnings_within_window: bool
    dividend_within_window: bool
    reason: str


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _days_apart(as_of: datetime, event_at: datetime) -> float:
    delta = _ensure_utc(event_at) - _ensure_utc(as_of)
    return abs(delta.total_seconds()) / 86_400


def compute_event_proximity_risk(
    as_of: datetime,
    earnings_dates: list[datetime],
    dividend_dates: list[datetime],
    *,
    earnings_window_days: int = 5,
    dividend_window_days: int = 3,
) -> EventProximityResult:
    """Return proximity risk when instrument is near earnings or ex-dividend date."""
    as_of_utc = _ensure_utc(as_of)

    nearest_earnings: datetime | None = None
    nearest_earnings_days: float | None = None
    for event_at in earnings_dates:
        days = _days_apart(as_of_utc, event_at)
        if nearest_earnings_days is None or days < nearest_earnings_days:
            nearest_earnings_days = days
            nearest_earnings = _ensure_utc(event_at)

    nearest_dividend: datetime | None = None
    nearest_dividend_days: float | None = None
    for event_at in dividend_dates:
        days = _days_apart(as_of_utc, event_at)
        if nearest_dividend_days is None or days < nearest_dividend_days:
            nearest_dividend_days = days
            nearest_dividend = _ensure_utc(event_at)

    earnings_within = (
        nearest_earnings_days is not None and nearest_earnings_days <= earnings_window_days
    )
    dividend_within = (
        nearest_dividend_days is not None and nearest_dividend_days <= dividend_window_days
    )

    if earnings_within and dividend_within:
        event_type = ProximityEventType.BOTH
        nearest_at = nearest_earnings if (nearest_earnings_days or 999) <= (nearest_dividend_days or 999) else nearest_dividend
        nearest_days = min(nearest_earnings_days or 999, nearest_dividend_days or 999)
        reason = (
            f"Within {earnings_window_days}d of earnings and "
            f"{dividend_window_days}d of ex-dividend ({nearest_days:.1f}d to nearest)"
        )
    elif earnings_within:
        event_type = ProximityEventType.EARNINGS
        nearest_at = nearest_earnings
        nearest_days = nearest_earnings_days
        reason = f"Within {earnings_window_days}d of earnings ({nearest_days:.1f}d away)"
    elif dividend_within:
        event_type = ProximityEventType.DIVIDEND
        nearest_at = nearest_dividend
        nearest_days = nearest_dividend_days
        reason = f"Within {dividend_window_days}d of ex-dividend ({nearest_days:.1f}d away)"
    else:
        candidates = [
            (nearest_earnings_days, nearest_earnings),
            (nearest_dividend_days, nearest_dividend),
        ]
        valid = [(days, at) for days, at in candidates if days is not None and at is not None]
        if valid:
            nearest_days, nearest_at = min(valid, key=lambda item: item[0])
        else:
            nearest_days, nearest_at = None, None
        event_type = ProximityEventType.NONE
        reason = "No earnings or dividend events within configured proximity windows"

    return EventProximityResult(
        is_at_risk=earnings_within or dividend_within,
        event_type=event_type,
        days_to_nearest_event=nearest_days,
        nearest_event_at=nearest_at,
        earnings_within_window=earnings_within,
        dividend_within_window=dividend_within,
        reason=reason,
    )


def proximity_window_end(as_of: datetime, *, earnings_window_days: int, dividend_window_days: int) -> datetime:
    """Upper bound for loading upcoming events from persistence."""
    return _ensure_utc(as_of) + timedelta(days=max(earnings_window_days, dividend_window_days) + 1)
