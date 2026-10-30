"""Tests that maneuver sizing respects the operator's portfolio_size setting."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone

from app.core.config import settings
from app.services.risk.engine import PortfolioState, RiskEngine, RiskParameters
from app.services.risk.maneuver_generator import ManeuverGenerator


def _make_df(seed: int = 0, trend: float = 0.002) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 300
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="D")
    close = 100 * np.cumprod(1 + rng.normal(0, 0.02, n) + trend)
    return pd.DataFrame(
        {
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, n),
        },
        index=dates,
    )


class TestPortfolioSizing:
    def test_risk_engine_small_portfolio_caps_position(self):
        engine = RiskEngine(RiskParameters(portfolio_size=500.0))
        result = engine.compute(
            ticker="AAPL",
            direction="long",
            entry_price=150.0,
            confidence=0.80,
            atr=3.0,
        )
        assert result.is_tradeable
        per_position_cap = 500.0 * settings.MAX_POSITION_PCT / 100
        assert result.position_size_usd <= per_position_cap
        assert result.position_size_usd <= 500.0

    def test_risk_engine_default_portfolio_would_oversize_small_account(self):
        """Regression: singleton/default 100k engine must not size a $500 account."""
        default_engine = RiskEngine(RiskParameters(portfolio_size=100_000.0))
        small_engine = RiskEngine(RiskParameters(portfolio_size=500.0))

        default = default_engine.compute(
            ticker="AAPL", direction="long", entry_price=150.0, confidence=0.80, atr=3.0
        )
        small = small_engine.compute(
            ticker="AAPL", direction="long", entry_price=150.0, confidence=0.80, atr=3.0
        )

        assert default.is_tradeable and small.is_tradeable
        assert default.position_size_usd > 500.0
        assert small.position_size_usd < default.position_size_usd

    def test_maneuver_generator_wires_portfolio_size_to_risk_engine(self):
        gen = ManeuverGenerator(portfolio_size=500.0)
        assert gen.risk_engine.params.portfolio_size == 500.0

    def test_maneuver_generator_caps_all_tradeable_maneuvers_at_portfolio(self):
        from app.services.risk.maneuver_generator import ManeuverOutput
        from app.services.risk.portfolio_sizing import allocate_deploy_budget

        gen = ManeuverGenerator(portfolio_size=500.0)
        outs = allocate_deploy_budget(
            [
                ManeuverOutput(
                    rank=i + 1,
                    ticker=f"T{i}",
                    strategy_type="momentum",
                    direction="long",
                    entry_zone_low=100.0,
                    entry_zone_high=101.0,
                    exit_zone_low=110.0,
                    exit_zone_high=111.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    invalidation_level=94.0,
                    risk_percent=8.0,
                    position_size_usd=800.0,
                    expected_return_low=3.0,
                    expected_return_high=6.0,
                    expected_pnl_low=64.0,
                    expected_pnl_high=128.0,
                    confidence=0.7 - i * 0.04,
                    time_horizon="1–5 days",
                    catalyst="test",
                    rationale="test",
                    execution_plan="Размер: $800.",
                )
                for i in range(8)
            ],
            gen.portfolio_size,
        )
        tradeable = [m for m in outs if not m.is_no_trade]

        per_position_cap = 500.0 * settings.MAX_POSITION_PCT / 100
        max_exposure = 500.0 * settings.MAX_PORTFOLIO_EXPOSURE_PCT / 100

        for m in tradeable:
            assert m.position_size_usd <= per_position_cap + 1e-6
            assert m.position_size_usd <= 500.0

        total = sum(m.position_size_usd for m in tradeable)
        assert total <= max_exposure + 1e-6
        from app.services.risk.portfolio_sizing import min_proposal_notional_usd

        floor = min_proposal_notional_usd(500.0)
        for m in tradeable:
            assert m.position_size_usd + 1e-6 >= floor

    def test_enforce_portfolio_limits_scales_batch_exposure(self):
        gen = ManeuverGenerator(portfolio_size=500.0)
        from app.services.risk.maneuver_generator import ManeuverOutput

        oversized = [
            ManeuverOutput(
                rank=1,
                ticker="A",
                strategy_type="momentum",
                direction="long",
                entry_zone_low=100.0,
                entry_zone_high=101.0,
                exit_zone_low=110.0,
                exit_zone_high=111.0,
                stop_loss=95.0,
                take_profit=110.0,
                invalidation_level=94.0,
                risk_percent=2.0,
                position_size_usd=400.0,
                expected_return_low=3.0,
                expected_return_high=6.0,
                expected_pnl_low=12.0,
                expected_pnl_high=24.0,
                confidence=0.7,
                time_horizon="1–5 days",
                catalyst="test",
                rationale="test",
                execution_plan="test",
            ),
            ManeuverOutput(
                rank=2,
                ticker="B",
                strategy_type="momentum",
                direction="long",
                entry_zone_low=100.0,
                entry_zone_high=101.0,
                exit_zone_low=110.0,
                exit_zone_high=111.0,
                stop_loss=95.0,
                take_profit=110.0,
                invalidation_level=94.0,
                risk_percent=2.0,
                position_size_usd=400.0,
                expected_return_low=3.0,
                expected_return_high=6.0,
                expected_pnl_low=12.0,
                expected_pnl_high=24.0,
                confidence=0.7,
                time_horizon="1–5 days",
                catalyst="test",
                rationale="test",
                execution_plan="test",
            ),
        ]
        clamped = gen._enforce_portfolio_limits(oversized)
        total = sum(m.position_size_usd for m in clamped if not m.is_no_trade)
        max_exposure = 500.0 * settings.MAX_PORTFOLIO_EXPOSURE_PCT / 100
        assert total <= max_exposure + 1e-6

    def test_tiny_leftover_budget_is_not_a_four_dollar_ticket(self):
        engine = RiskEngine(RiskParameters(portfolio_size=800.0))
        leftover = engine.compute(
            ticker="NSFT",
            direction="long",
            entry_price=100.0,
            confidence=0.80,
            atr=40.0,
            portfolio_state=PortfolioState(total_exposure_usd=630.0, open_positions=12),
        )
        assert leftover.is_tradeable is False

    def test_cap_800_ticket_is_at_least_min_notional(self):
        from app.services.risk.portfolio_sizing import min_proposal_notional_usd

        engine = RiskEngine(RiskParameters(portfolio_size=800.0))
        out = engine.compute(
            ticker="AAPL",
            direction="long",
            entry_price=150.0,
            confidence=0.80,
            atr=3.0,
        )
        assert out.is_tradeable
        assert out.position_size_usd + 1e-6 >= min_proposal_notional_usd(800.0)


def test_resolve_portfolio_size_usd_keeps_explicit_small_cap():
    from app.services.risk.portfolio_sizing import resolve_portfolio_size_usd

    assert resolve_portfolio_size_usd(250.0) == 250.0
    assert resolve_portfolio_size_usd(0.0) == 10_000.0
    assert resolve_portfolio_size_usd(None) == 10_000.0


def test_resolve_deploy_cap_never_replaces_small_settings_with_10k():
    from app.services.risk.portfolio_sizing import resolve_deploy_cap_for_sizing

    assert resolve_deploy_cap_for_sizing(250.0, 0.0) == 250.0
    assert resolve_deploy_cap_for_sizing(250.0, 10_000.0) == 250.0
    assert resolve_deploy_cap_for_sizing(250.0, 100.0) == 100.0
    assert resolve_deploy_cap_for_sizing(0.0, 5_000.0) == 5_000.0
    both_zero = resolve_deploy_cap_for_sizing(0.0, 0.0)
    assert both_zero == 10_000.0


def test_allocate_prefers_higher_confidence_and_respects_cap_250():
    from app.services.risk.maneuver_generator import ManeuverOutput
    from app.services.risk.portfolio_sizing import allocate_deploy_budget

    def _m(ticker: str, conf: float, usd: float) -> ManeuverOutput:
        return ManeuverOutput(
            rank=1,
            ticker=ticker,
            strategy_type="momentum",
            direction="long",
            entry_zone_low=100.0,
            entry_zone_high=101.0,
            exit_zone_low=110.0,
            exit_zone_high=111.0,
            stop_loss=95.0,
            take_profit=110.0,
            invalidation_level=94.0,
            risk_percent=2.0,
            position_size_usd=usd,
            expected_return_low=3.0,
            expected_return_high=6.0,
            expected_pnl_low=12.0,
            expected_pnl_high=24.0,
            confidence=conf,
            time_horizon="1–5 days",
            catalyst="test",
            rationale="test",
            execution_plan="Размер: $800.",
        )

    outs = allocate_deploy_budget(
        [_m("AAA", 0.90, 800.0), _m("BBB", 0.12, 800.0)],
        250.0,
    )
    tradeable = [m for m in outs if not m.is_no_trade]
    per_name = 250.0 * settings.MAX_POSITION_PCT / 100
    max_book = 250.0 * settings.MAX_PORTFOLIO_EXPOSURE_PCT / 100
    assert tradeable
    for m in tradeable:
        assert m.position_size_usd <= per_name + 1e-6
        assert m.position_size_usd < 50
        assert abs(m.position_size_usd - 800.0) > 100
    total = sum(m.position_size_usd for m in tradeable)
    assert total <= max_book + 1e-6
    by_t = {m.ticker: m.position_size_usd for m in tradeable}
    if "AAA" in by_t and "BBB" in by_t:
        assert by_t["AAA"] > by_t["BBB"]


def test_capped_conviction_weights_leave_leftover_as_cash():
    from app.services.risk.portfolio_sizing import capped_conviction_weights

    weights = capped_conviction_weights([0.9, 0.12], name_cap_frac=0.125)
    assert weights[0] == pytest.approx(0.125)
    assert weights[1] == pytest.approx(0.125 * 0.12 / 0.9)
    assert weights[1] < weights[0]
    assert sum(weights) < 1.0 - 1e-6


def test_allocate_scales_by_conviction_not_flat_name_cap():
    from app.services.risk.maneuver_generator import ManeuverOutput
    from app.services.risk.portfolio_sizing import allocate_deploy_budget

    def _m(ticker: str, conf: float) -> ManeuverOutput:
        return ManeuverOutput(
            rank=1,
            ticker=ticker,
            strategy_type="momentum",
            direction="long",
            entry_zone_low=100.0,
            entry_zone_high=101.0,
            exit_zone_low=110.0,
            exit_zone_high=111.0,
            stop_loss=95.0,
            take_profit=110.0,
            invalidation_level=94.0,
            risk_percent=2.0,
            position_size_usd=800.0,
            expected_return_low=3.0,
            expected_return_high=6.0,
            expected_pnl_low=12.0,
            expected_pnl_high=24.0,
            confidence=conf,
            time_horizon="1–5 days",
            catalyst="test",
            rationale="test",
            execution_plan="Размер: $800.",
        )

    outs = allocate_deploy_budget(
        [_m("EQMX", 0.90), _m("AMZN", 0.45)],
        5_000.0,
    )
    by = {m.ticker: m.position_size_usd for m in outs if not m.is_no_trade}
    assert "EQMX" in by
    if "AMZN" in by:
        assert by["AMZN"] < by["EQMX"] * 0.65
        per_name = max(by["EQMX"], 1.0)
        assert abs(by["AMZN"] / per_name - 0.45 / 0.90) < 0.08
    else:
        # Weak name dropped under min ticket — still not a flat 10% fill of every idea.
        assert by["EQMX"] > 0


def test_enforce_hard_caps_clips_stale_800_on_250_book():
    from app.services.risk.maneuver_generator import ManeuverOutput
    from app.services.risk.portfolio_sizing import enforce_hard_deploy_caps

    stale = ManeuverOutput(
        rank=1,
        ticker="AAA",
        strategy_type="momentum",
        direction="long",
        entry_zone_low=100.0,
        entry_zone_high=101.0,
        exit_zone_low=110.0,
        exit_zone_high=111.0,
        stop_loss=95.0,
        take_profit=110.0,
        invalidation_level=94.0,
        risk_percent=8.0,
        position_size_usd=800.0,
        expected_return_low=3.0,
        expected_return_high=6.0,
        expected_pnl_low=12.0,
        expected_pnl_high=24.0,
        confidence=0.8,
        time_horizon="1–5 days",
        catalyst="test",
        rationale="test",
        execution_plan="Размер: $800.",
    )
    enforce_hard_deploy_caps([stale], 250.0)
    per_name = 250.0 * settings.MAX_POSITION_PCT / 100
    assert stale.position_size_usd <= per_name + 1e-6
    assert stale.position_size_usd != 800.0


def test_generator_cap_250_never_emits_800_tickets():
    gen = ManeuverGenerator(portfolio_size=250.0)
    assert gen.portfolio_size == 250.0
    assert gen.risk_engine.params.portfolio_size == 250.0
    from app.services.risk.maneuver_generator import ManeuverOutput
    from app.services.risk.portfolio_sizing import allocate_deploy_budget

    fat = ManeuverOutput(
        rank=1,
        ticker="AAA",
        strategy_type="momentum",
        direction="long",
        entry_zone_low=100.0,
        entry_zone_high=101.0,
        exit_zone_low=110.0,
        exit_zone_high=111.0,
        stop_loss=95.0,
        take_profit=110.0,
        invalidation_level=94.0,
        risk_percent=8.0,
        position_size_usd=800.0,
        expected_return_low=3.0,
        expected_return_high=6.0,
        expected_pnl_low=64.0,
        expected_pnl_high=128.0,
        confidence=0.85,
        time_horizon="1–5 days",
        catalyst="test",
        rationale="test",
        execution_plan="Размер: $800.",
    )
    allocate_deploy_budget([fat], gen.portfolio_size)
    assert fat.position_size_usd <= 25.0 + 1e-6
    assert fat.position_size_usd < 100.0


def test_generate_cap_250_emits_tradeable_under_name_cap():
    market_data = {f"T{i}": _make_df(i, trend=0.003 + i * 0.0002) for i in range(8)}
    gen = ManeuverGenerator(portfolio_size=250.0, confidence_threshold=0.05)
    outs = gen.generate(market_data=market_data)
    tradeable = [m for m in outs if not m.is_no_trade]
    assert tradeable, "generate() must not empty the book on a $250 cap"
    per_name = 250.0 * settings.MAX_POSITION_PCT / 100
    max_book = 250.0 * settings.MAX_PORTFOLIO_EXPOSURE_PCT / 100
    for m in tradeable:
        assert m.position_size_usd <= per_name + 1e-6
        assert m.position_size_usd <= 250.0
        assert m.position_size_usd < 100.0
        assert abs(m.position_size_usd - 800.0) > 100
    assert sum(m.position_size_usd for m in tradeable) <= max_book + 1e-6

