"""Tests for honest maneuver profit projection (vol + horizon + TP probability)."""
from __future__ import annotations

import pytest

from app.services.risk.profit_projection import (
    compute_profit_projection,
    horizon_to_days,
    tp_hit_probability,
    tp_return_decimal,
)
from types import SimpleNamespace


class TestHorizonParsing:
    def test_horizon_to_days_midpoint(self):
        assert horizon_to_days("1–3 дня") == pytest.approx(2.0, rel=0.01)


class TestTpReturn:
    def test_long_tp_return(self):
        assert tp_return_decimal("long", 100.0, 110.0) == pytest.approx(0.10)

    def test_short_tp_return(self):
        assert tp_return_decimal("short", 100.0, 90.0) == pytest.approx(0.10)


class TestTpHitProbability:
    def test_far_tp_has_low_probability_on_short_remaining_time(self):
        # 10% TP with ~1 day left and 2% daily vol → unlikely
        p = tp_hit_probability(
            "long",
            entry_price=100.0,
            take_profit=110.0,
            daily_vol=0.02,
            remaining_days=1.0,
            drift_return=0.0,
        )
        assert p < 0.35

    def test_near_tp_has_higher_probability(self):
        p = tp_hit_probability(
            "long",
            entry_price=100.0,
            take_profit=101.0,
            daily_vol=0.02,
            remaining_days=5.0,
            drift_return=0.01,
        )
        assert p > 0.4


class TestComputeProfitProjection:
    def test_expected_pnl_much_smaller_than_full_tp_on_short_horizon(self):
        proj = compute_profit_projection(
            direction="long",
            entry_price=100.0,
            take_profit=110.0,
            stop_loss=96.0,
            position_size_usd=500.0,
            time_horizon="1–3 дня",
            daily_vol=0.02,
            round_trip_fees_usd=2.0,
        )
        assert proj is not None
        assert proj.tp_profit_usd > 40.0
        assert proj.expected_pnl_high < proj.tp_profit_usd * 0.6
        assert proj.tp_hit_probability < 0.5

    def test_hierarchy_interval_tightens_band(self):
        interval = SimpleNamespace(
            horizon_days=10,
            p10=-0.05,
            p90=0.05,
            rolling_volatility=0.02,
            confidence_multiplier=1.645,
        )
        proxy = compute_profit_projection(
            direction="long",
            entry_price=50.0,
            take_profit=55.0,
            stop_loss=48.0,
            position_size_usd=1_000.0,
            time_horizon="5–10 дней",
            interval_forecast=interval,
        )
        assert proxy is not None
        assert proxy.data_source == "hierarchy"

    def test_caps_optimistic_return_at_tp(self):
        proj = compute_profit_projection(
            direction="long",
            entry_price=100.0,
            take_profit=102.0,
            stop_loss=95.0,
            position_size_usd=300.0,
            time_horizon="10–20 дней",
            daily_vol=0.05,
        )
        assert proj is not None
        assert proj.expected_return_high_pct <= tp_return_decimal("long", 100.0, 102.0) * 100 + 0.01
