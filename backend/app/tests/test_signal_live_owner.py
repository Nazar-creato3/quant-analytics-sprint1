"""GA16-121: missing user row must not aggregate all closed maneuvers."""
from __future__ import annotations

import asyncio

from app.services.monitoring.signal_performance import (
    compute_live_maneuver_performance,
    empty_live_performance,
)


def test_empty_owner_does_not_need_db() -> None:
    out = empty_live_performance()
    assert out.sample_size == 0
    assert out.win_rate is None
    assert out.sharpe_ratio is None


def test_blank_owner_id_skips_global_query() -> None:
    out = asyncio.run(compute_live_maneuver_performance(None, owner_user_id=""))  # type: ignore[arg-type]
    assert out.sample_size == 0
    assert out.expectancy_usd is None
