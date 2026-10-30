"""Hosting payment reminder windows (7 and 3 days). No live API required."""
from __future__ import annotations

from datetime import date, datetime


def days_until_paid(paid_until: str, today: date | None = None) -> int | None:
    if not paid_until.strip():
        return None
    today = today or date.today()
    due = datetime.fromisoformat(paid_until).date()
    return (due - today).days


def reminder_due(today: date, paid_until: date) -> bool:
    remaining = (paid_until - today).days
    return remaining in {7, 3} or remaining <= 0
