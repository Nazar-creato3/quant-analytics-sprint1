"""Known FOMC meeting windows — used when live macro calendar DB is empty."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


# Federal Reserve FOMC two-day meeting start dates (US calendar).
_FOMC_MEETING_STARTS: tuple[date, ...] = (
    date(2025, 1, 29),
    date(2025, 3, 19),
    date(2025, 5, 7),
    date(2025, 6, 18),
    date(2025, 7, 30),
    date(2025, 9, 17),
    date(2025, 11, 6),
    date(2025, 12, 17),
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 11, 4),
    date(2026, 12, 16),
    date(2027, 1, 27),
    date(2027, 3, 17),
)


def next_fomc_window(
    as_of: datetime | None = None,
    *,
    decision_day_offset: int = 1,
) -> dict[str, str | datetime] | None:
    """Return the next FOMC decision window after *as_of*."""
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.date()

    for start in _FOMC_MEETING_STARTS:
        if start < today:
            continue
        decision_day = start + timedelta(days=decision_day_offset)
        window_end = start + timedelta(days=decision_day_offset)
        decision_at = datetime(
            decision_day.year,
            decision_day.month,
            decision_day.day,
            19,
            0,
            tzinfo=timezone.utc,
        )
        return {
            "event_name": "FOMC rate decision",
            "event_type": "macro",
            "window_start": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
            "scheduled_at": decision_at,
            "window_end": datetime(window_end.year, window_end.month, window_end.day, tzinfo=timezone.utc),
            "source": "fomc_calendar",
        }
    return None
