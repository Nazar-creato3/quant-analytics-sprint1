"""GA16-265: a short exit follows the direction value, not the enum text."""
from __future__ import annotations

from types import SimpleNamespace

from app.db.models import SignalDirection
from app.services.portfolio.barrier_close import _exit_price_for_reason


def test_short_stop_exit_uses_direction_value() -> None:
    maneuver = SimpleNamespace(
        direction=SignalDirection.SHORT,
        stop_loss=110.0,
        take_profit=90.0,
        invalidation_level=None,
        exit_zone_high=None,
        exit_zone_low=None,
    )
    assert _exit_price_for_reason(maneuver, "stop", 115.0) == 110.0
