"""Recalc cache on book/price events."""
from __future__ import annotations

from app.services.event_bus.bus import get_bus
from app.services.risk_engine.service import invalidate


def register() -> None:
    bus = get_bus()
    bus.subscribe("position.changed", lambda _e: invalidate())
    bus.subscribe("forecast.updated", lambda _e: invalidate())
