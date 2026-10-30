"""Unit and property-based tests for AntiLossGuard."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.config import Settings
from app.domain.deal_intent_enums import DealIntentDirection, RiskTag
from app.domain.enums import AssetCategory, Strategy
from app.domain.profile import ProfileMode
from app.services.control_fabric.anti_loss_guard import (
    CORRELATION_CLUSTER_THRESHOLD,
    AntiLossGuard,
    cluster_exposure_usd,
    parse_market_regime,
    strategy_regime_compatible,
)
from app.services.control_fabric.risk_gate import RiskGate, volatility_scaled_position_size
from app.services.control_fabric.types import OpenPositionExposure, RiskGateOutcome
from app.services.strategy.types import GridMode, MarketRegime
from app.tests.test_approval_policy_engine import _context, _intent, _profile

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _settings(**overrides: object) -> Settings:
    defaults = {
        "PAPER_TRADING_MIN_DAYS": 30,
        "PAPER_SHARPE_MIN_THRESHOLD": 0.5,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _sleeve(**overrides: object):
    from app.domain.enums import SleeveStatus
    from app.domain.sleeve import SleeveRead

    defaults = {
        "id": "sleeve-1",
        "profile_id": "user-1",
        "name": "Core",
        "category": AssetCategory.EQUITIES,
        "capital_allocation_pct": Decimal("60"),
        "risk_budget": Decimal("10000"),
        "status": SleeveStatus.ACTIVE,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return SleeveRead(**defaults)


class TestParseMarketRegime:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("trend_up", MarketRegime.TREND_UP),
            ("trend", MarketRegime.TREND_UP),
            ("high_vol", MarketRegime.HIGH_VOL),
            ("range", MarketRegime.RANGE),
            ("unknown", MarketRegime.UNKNOWN),
            ("garbage", MarketRegime.UNKNOWN),
        ],
    )
    def test_normalizes_regime_strings(self, raw: str, expected: MarketRegime):
        assert parse_market_regime(raw) == expected


class TestStrategyRegimeCompatible:
    def test_grid_allows_range_and_low_vol(self):
        assert strategy_regime_compatible(Strategy.GRID, MarketRegime.RANGE, DealIntentDirection.LONG)
        assert strategy_regime_compatible(Strategy.GRID, MarketRegime.LOW_VOL, DealIntentDirection.LONG)

    def test_grid_blocks_trend_up(self):
        assert not strategy_regime_compatible(
            Strategy.GRID, MarketRegime.TREND_UP, DealIntentDirection.LONG
        )

    def test_trend_long_requires_trend_up(self):
        assert strategy_regime_compatible(
            Strategy.TREND, MarketRegime.TREND_UP, DealIntentDirection.LONG
        )
        assert not strategy_regime_compatible(
            Strategy.TREND, MarketRegime.TREND_DOWN, DealIntentDirection.LONG
        )

    def test_unknown_regime_always_compatible(self):
        assert strategy_regime_compatible(
            Strategy.GRID, MarketRegime.UNKNOWN, DealIntentDirection.LONG
        )


class TestAntiLossGuardChecks:
    def test_blocks_insufficient_liquidity_spread(self):
        guard = AntiLossGuard()
        intent = _intent(max_spread_bps=10)
        context = _context(instrument_spread_bps=15.0)

        result = guard.check(intent, _profile(), context)
        assert result is not None
        assert result.allowed is False
        assert "liquidity" in result.reason

    def test_blocks_against_market_regime(self):
        guard = AntiLossGuard()
        intent = _intent(strategy=Strategy.GRID, exit_logic={"grid_mode": GridMode.POINT.value})
        context = _context(market_regime="trend_up")

        result = guard.check(intent, _profile(), context)
        assert result is not None
        assert "regime" in result.reason

    def test_blocks_event_risk_grid_same_instrument(self):
        guard = AntiLossGuard()
        intent = _intent(
            strategy=Strategy.GRID,
            risk_tag=RiskTag.EVENT_RISK,
            exit_logic={"grid_mode": GridMode.POINT.value},
        )
        context = _context(market_regime="range")

        result = guard.check(intent, _profile(), context)
        assert result is not None
        assert "event-risk and grid" in result.reason

    def test_blocks_open_grid_with_event_risk_intent(self):
        guard = AntiLossGuard()
        intent = _intent(risk_tag=RiskTag.EVENT_RISK, instrument_id=101)
        positions = [
            OpenPositionExposure(
                instrument_id=101,
                sleeve_id="sleeve-1",
                market_value_usd=Decimal("1000"),
                metadata={"strategy": Strategy.GRID.value},
            )
        ]

        result = guard.check(intent, _profile(), _context(), open_positions=positions)
        assert result is not None
        assert "grid exposure" in result.reason

    def test_blocks_correlated_cluster_exposure(self):
        guard = AntiLossGuard()
        profile = _profile(
            max_daily_loss_abs=Decimal("10000"),
            diversification_policy={"max_correlation_cluster_pct": 10},
        )
        intent = _intent(instrument_id=101)
        positions = [
            OpenPositionExposure(
                instrument_id=202,
                sleeve_id="sleeve-1",
                market_value_usd=Decimal("900"),
            )
        ]

        result = guard.check(
            intent,
            profile,
            _context(),
            sleeve=_sleeve(risk_budget=Decimal("10000")),
            open_positions=positions,
            instrument_correlations={202: 0.85},
            proposed_size_usd=Decimal("200"),
        )
        assert result is not None
        assert "cluster" in result.reason

    def test_blocks_news_lock_on_instrument(self):
        guard = AntiLossGuard()
        intent = _intent(instrument_id=101)
        context = _context(news_locked_instrument_ids=frozenset({101}))

        result = guard.check(intent, _profile(), context)
        assert result is not None
        assert "news_lock" in result.reason

    def test_blocks_intent_news_lock_flag(self):
        guard = AntiLossGuard()
        intent = _intent(news_lock=True)

        result = guard.check(intent, _profile(), _context())
        assert result is not None
        assert "news_lock" in result.reason

    def test_blocks_live_without_paper_signoff(self):
        guard = AntiLossGuard(settings=_settings())
        profile = _profile(
            mode=ProfileMode.LIVE,
            paper_trading_days=5,
            paper_sharpe=0.2,
        )

        result = guard.check(_intent(), profile, _context())
        assert result is not None
        assert "paper sign-off" in result.reason

    def test_passes_when_all_checks_ok(self):
        guard = AntiLossGuard()
        intent = _intent(strategy=Strategy.TREND)
        context = _context(market_regime="trend_up")

        result = guard.check(intent, _profile(), context)
        assert result is None


class TestClusterExposure:
    def test_same_instrument_counts_toward_cluster(self):
        positions = [
            OpenPositionExposure(
                instrument_id=101,
                sleeve_id="sleeve-1",
                market_value_usd=Decimal("500"),
            )
        ]
        total = cluster_exposure_usd(101, positions, {})
        assert total == Decimal("500")

    def test_high_correlation_pairs_form_cluster(self):
        positions = [
            OpenPositionExposure(
                instrument_id=202,
                sleeve_id="sleeve-1",
                market_value_usd=Decimal("300"),
            )
        ]
        total = cluster_exposure_usd(101, positions, {202: 0.75})
        assert total == Decimal("300")

    def test_below_threshold_excluded(self):
        positions = [
            OpenPositionExposure(
                instrument_id=202,
                sleeve_id="sleeve-1",
                market_value_usd=Decimal("300"),
            )
        ]
        total = cluster_exposure_usd(101, positions, {202: 0.69})
        assert total == Decimal("0")


class TestRiskGateAntiLossIntegration:
    def test_risk_gate_runs_anti_loss_before_correlation(self):
        gate = RiskGate()
        intent = _intent(strategy=Strategy.GRID, exit_logic={"grid_mode": GridMode.POINT.value})
        context = _context(market_regime="trend_up", max_correlation_with_portfolio=0.1)

        result = gate.check_intent(intent, _profile(), _sleeve(), context)
        assert result.allowed is False
        assert result.outcome == RiskGateOutcome.BLOCKED
        assert "regime" in result.reason

    def test_volatility_scaled_position_size_at_boundary(self):
        at_target = volatility_scaled_position_size(
            base_size_usd=Decimal("1000"),
            atr=2.0,
            price=100.0,
            profile_volatility_tolerance=0.5,
            target_atr_pct=0.02,
        )
        assert at_target.scale_factor <= 1.0

        high_vol = volatility_scaled_position_size(
            base_size_usd=Decimal("1000"),
            atr=10.0,
            price=100.0,
            profile_volatility_tolerance=0.5,
        )
        assert high_vol.adjusted_size_usd < high_vol.base_size_usd


class TestAntiLossGuardFuzz:
    @given(
        spread=st.floats(min_value=0.0, max_value=200.0, allow_nan=False),
        max_spread=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=200, deadline=None)
    def test_liquidity_boundary(self, spread: float, max_spread: int):
        guard = AntiLossGuard()
        intent = _intent(max_spread_bps=max_spread)
        context = _context(instrument_spread_bps=spread)
        result = guard.check(intent, _profile(), context)

        if spread > max_spread:
            assert result is not None
            assert result.allowed is False
        elif spread > 100.0:
            assert result is not None
            assert result.allowed is False

    @given(
        correlation=st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
        ),
        exposure=st.decimals(min_value=0, max_value=50000, places=2),
        proposed=st.decimals(min_value=0, max_value=50000, places=2),
    )
    @settings(max_examples=200, deadline=None)
    def test_cluster_correlation_threshold_boundary(
        self,
        correlation: float,
        exposure: Decimal,
        proposed: Decimal,
    ):
        guard = AntiLossGuard(correlation_cluster_threshold=CORRELATION_CLUSTER_THRESHOLD)
        profile = _profile(
            max_daily_loss_abs=Decimal("10000"),
            diversification_policy={"max_correlation_cluster_pct": 25},
        )
        positions = [
            OpenPositionExposure(
                instrument_id=202,
                sleeve_id="sleeve-1",
                market_value_usd=exposure,
            )
        ]
        result = guard.check(
            _intent(instrument_id=101),
            profile,
            _context(),
            sleeve=_sleeve(risk_budget=Decimal("10000")),
            open_positions=positions,
            instrument_correlations={202: correlation},
            proposed_size_usd=proposed,
        )
        limit = Decimal("2500")
        in_cluster = correlation > CORRELATION_CLUSTER_THRESHOLD
        if not in_cluster or exposure <= 0:
            return
        total = exposure + proposed
        if total > limit:
            assert result is not None
            assert not result.allowed

    @given(
        atr=st.floats(min_value=0.001, max_value=50.0, allow_nan=False),
        price=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False),
        tolerance=st.floats(min_value=0.01, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=150, deadline=None)
    def test_volatility_scale_never_exceeds_base(
        self,
        atr: float,
        price: float,
        tolerance: float,
    ):
        result = volatility_scaled_position_size(
            base_size_usd=Decimal("1000"),
            atr=atr,
            price=price,
            profile_volatility_tolerance=tolerance,
        )
        assert result.adjusted_size_usd <= result.base_size_usd
        assert 0.0 < result.scale_factor <= 1.0

    @given(
        regime=st.sampled_from(list(MarketRegime)),
        strategy=st.sampled_from(list(Strategy)),
        direction=st.sampled_from(list(DealIntentDirection)),
    )
    @settings(max_examples=200, deadline=None)
    def test_regime_compatibility_deterministic(
        self,
        regime: MarketRegime,
        strategy: Strategy,
        direction: DealIntentDirection,
    ):
        first = strategy_regime_compatible(strategy, regime, direction)
        second = strategy_regime_compatible(strategy, regime, direction)
        assert first == second

    @given(
        daily_loss=st.decimals(min_value=0, max_value=100000, places=2),
        limit=st.decimals(min_value=1, max_value=100000, places=2),
    )
    @settings(max_examples=150, deadline=None)
    def test_daily_loss_kill_switch_boundary(self, daily_loss: Decimal, limit: Decimal):
        gate = RiskGate()
        profile = _profile(
            max_daily_loss_abs=limit,
            diversification_policy={"max_correlation_cluster_pct": 100},
        )
        from app.services.control_fabric.types import RiskSnapshot

        snapshot = RiskSnapshot(profile_daily_loss_abs=daily_loss)

        result = gate.check_intent(_intent(), profile, _sleeve(), _context(), snapshot=snapshot)
        if daily_loss >= limit:
            assert result.triggers_kill_switch
            assert result.outcome == RiskGateOutcome.BREACH_CRITICAL
        else:
            assert not result.triggers_kill_switch or result.allowed
