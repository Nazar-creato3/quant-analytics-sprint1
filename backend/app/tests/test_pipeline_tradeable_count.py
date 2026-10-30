"""Pipeline tradeable_count must match persisted maneuver rows."""
from __future__ import annotations

from app.db.models import StrategyType
from app.tasks.pipeline import _map_strategy
from app.services.risk.maneuver_generator import ManeuverOutput


def _persisted_tradeable_count(outputs: list[ManeuverOutput]) -> int:
    n = 0
    for out in outputs:
        st = _map_strategy(out.strategy_type)
        if (
            st != StrategyType.NO_TRADE
            and out.ticker not in ("—", "-")
            and out.direction != "neutral"
        ):
            n += 1
    return n


def test_tradeable_count_matches_generator_outputs():
    outputs = [
        ManeuverOutput(
            rank=1,
            ticker="AAPL",
            strategy_type="momentum",
            direction="long",
            entry_zone_low=1.0,
            entry_zone_high=1.1,
            exit_zone_low=None,
            exit_zone_high=None,
            stop_loss=0.9,
            take_profit=1.2,
            invalidation_level=0.85,
            risk_percent=1.0,
            position_size_usd=1000.0,
            expected_return_low=1.0,
            expected_return_high=2.0,
            expected_pnl_low=10.0,
            expected_pnl_high=20.0,
            confidence=0.55,
            time_horizon="1–5 days",
            catalyst="test",
            rationale="test",
            execution_plan="test",
        ),
        ManeuverOutput(
            rank=2,
            ticker="—",
            strategy_type="no_trade",
            direction="neutral",
            entry_zone_low=None,
            entry_zone_high=None,
            exit_zone_low=None,
            exit_zone_high=None,
            stop_loss=None,
            take_profit=None,
            invalidation_level=None,
            risk_percent=0.0,
            position_size_usd=0.0,
            expected_return_low=None,
            expected_return_high=None,
            expected_pnl_low=None,
            expected_pnl_high=None,
            confidence=0.0,
            time_horizon="—",
            catalyst="—",
            rationale="no edge",
            execution_plan="—",
            is_no_trade=True,
        ),
    ]
    assert _persisted_tradeable_count(outputs) == 1
    assert sum(1 for o in outputs if not o.is_no_trade) == 1
