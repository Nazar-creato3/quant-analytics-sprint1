"""MOEX trading calendar helpers. Last-buy day is T+1: previous session before record."""
from __future__ import annotations

from datetime import date, timedelta

# Fixture holidays used in tests (prompt 57). Not a full exchange calendar.
HOLIDAYS = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 7),
        date(2026, 2, 23),
        date(2026, 3, 9),
        date(2026, 5, 1),
        date(2026, 5, 11),
        date(2026, 6, 12),
        date(2026, 11, 4),
        date(2026, 12, 31),
    }
)


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in HOLIDAYS


def previous_trading_day(day: date) -> date:
    cursor = day - timedelta(days=1)
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def last_buy_date(record_date: date, *, from_broker: date | None = None) -> tuple[date, str]:
    """T+1: last session before record. Broker field wins; else MOEX calendar + label «расчёт»."""
    if from_broker is not None:
        return from_broker, "данные брокера"
    return previous_trading_day(record_date), "расчёт"
