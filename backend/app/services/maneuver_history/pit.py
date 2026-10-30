"""Point-in-time slices. A date after as_of in the signal set is a leak."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal


def business_sessions(start: date, count: int) -> list[date]:
    """Weekday sessions. The exchange holiday calendar is not in the repo."""
    if count < 1:
        return []
    out: list[date] = []
    day = start
    guard = start + timedelta(days=max(count * 3, 14))
    while len(out) < count and day <= guard:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def quarter_decision_indexes(sessions: list[date], *, min_history: int = 8) -> list[int]:
    """First weekday of Jan/Apr/Jul/Oct that still has a later session and enough history."""
    chosen: list[int] = []
    last = len(sessions) - 1
    for index in range(1, last):
        prev, cur = sessions[index - 1], sessions[index]
        if cur.month == prev.month:
            continue
        if cur.month not in (1, 4, 7, 10):
            continue
        if index < min_history:
            continue
        chosen.append(index)
    return chosen


def slice_dates(dates: list[date], as_of: date) -> list[date]:
    return [day for day in dates if day <= as_of]


def detect_leak(as_of: date, used: list[date]) -> bool:
    """True when a signal date is strictly after the decision date."""
    return any(day > as_of for day in used)


def returns_through(prices: list[Decimal], index: int) -> tuple[float, ...]:
    """Simple returns of prices[0:index] inclusive. Later prices are not read."""
    if index < 1:
        return tuple()
    window = prices[: index + 1]
    out: list[float] = []
    for prev, nxt in zip(window, window[1:]):
        if prev == 0:
            return tuple()
        out.append(float((nxt - prev) / prev))
    return tuple(out)
