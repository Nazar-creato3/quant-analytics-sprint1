"""Prompt 15 — 90-day historical replay validation (Binance / MOEX / Tinkoff)."""
from __future__ import annotations

import pytest

from app.domain.enums import AssetCategory, Strategy
from app.services.integration.historical_data import (
    KNOWN_GAPS,
    fetch_binance_bars,
    fetch_moex_bars,
    fetch_tinkoff_bars,
    generate_synthetic_bars,
)
from app.services.integration.pipeline import ValidationPipeline, run_combined_validation, run_validation_on_bars
from app.services.integration.types import VenueConfig
from app.tests.integration.conftest import _NOW
from app.domain.compliance import AccountType, Jurisdiction
from app.domain.enums import SleeveStatus
from app.domain.profile import (
    AutomationLevel,
    ExecutionStyle,
    ProfileMode,
    ProfileRead,
    RiskAppetite,
    TimeHorizon,
)
from app.domain.sleeve import SleeveRead
from decimal import Decimal

PERIOD_DAYS = 90
STRATEGIES = [Strategy.GRID, Strategy.TREND, Strategy.MEAN_REVERSION]


def _profile_for_venue(category: AssetCategory) -> ProfileRead:
    categories = [category, AssetCategory.ETF]
    if category == AssetCategory.CRYPTO:
        categories.append(AssetCategory.CRYPTO)
    return ProfileRead(
        id="profile-hist",
        risk_appetite=RiskAppetite.MODERATE,
        max_drawdown_pct=Decimal("15"),
        max_daily_loss_abs=Decimal("5000"),
        allowed_categories=categories,
        allowed_instrument_ids=[],
        approval_policy_id=None,
        time_horizon=TimeHorizon.SWING,
        execution_style=ExecutionStyle.ACTIVE,
        volatility_tolerance=0.6,
        hedge_preference=False,
        leverage_max=Decimal("1"),
        mode=ProfileMode.PAPER,
        automation_level=AutomationLevel.SEMI_AUTO,
        session_preferences={},
        news_sensitivity=0.5,
        event_sensitivity=0.5,
        diversification_policy={"max_correlation": 0.7},
        paper_trading_days=45,
        paper_sharpe=1.0,
        jurisdiction=Jurisdiction.GLOBAL,
        account_type=AccountType.PROFESSIONAL,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _sleeve_for(category: AssetCategory, sleeve_id: str) -> SleeveRead:
    return SleeveRead(
        id=sleeve_id,
        profile_id="profile-hist",
        name=sleeve_id,
        category=category,
        capital_allocation_pct=Decimal("40"),
        risk_budget=Decimal("30000"),
        status=SleeveStatus.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.integration
@pytest.mark.slow
class TestHistoricalReplayValidation:
    @pytest.mark.asyncio
    async def test_binance_90_day_replay(self):
        bars, stub = await fetch_binance_bars("BTC-USD", days=PERIOD_DAYS)
        if len(bars) < 30:
            bars = generate_synthetic_bars("BTC-USD", days=PERIOD_DAYS, seed=99)
            stub = True

        venue = VenueConfig("binance", "BTC-USD", 1001, AssetCategory.CRYPTO, "sleeve-crypto")
        profile = _profile_for_venue(AssetCategory.CRYPTO)
        sleeve = _sleeve_for(AssetCategory.CRYPTO, "sleeve-crypto")
        pipeline = ValidationPipeline(profile, sleeve)

        report = await run_validation_on_bars(
            pipeline,
            bars,
            venue=venue,
            strategy=Strategy.GRID,
            period_days=PERIOD_DAYS,
            used_stub_data=stub,
        )

        assert report.total_bars >= 30
        assert 0.0 <= report.win_rate <= 1.0
        assert report.max_drawdown_pct >= 0.0
        summary = report.summary()
        assert "rejected_reasons" in summary
        assert "held_reasons" in summary

    @pytest.mark.asyncio
    async def test_moex_90_day_replay(self):
        bars, stub = await fetch_moex_bars("SBER", days=PERIOD_DAYS)
        venue = VenueConfig("moex", "SBER", 2001, AssetCategory.EQUITIES, "sleeve-equity")
        profile = _profile_for_venue(AssetCategory.EQUITIES)
        sleeve = _sleeve_for(AssetCategory.EQUITIES, "sleeve-equity")
        pipeline = ValidationPipeline(profile, sleeve)

        report = await run_validation_on_bars(
            pipeline,
            bars,
            venue=venue,
            strategy=Strategy.TREND,
            period_days=PERIOD_DAYS,
            used_stub_data=stub,
        )

        assert report.source == "moex"
        assert report.period_days == PERIOD_DAYS

    @pytest.mark.asyncio
    async def test_tinkoff_90_day_replay(self):
        bars, stub = fetch_tinkoff_bars("GAZP", days=PERIOD_DAYS)
        assert len(bars) >= 30

        venue = VenueConfig("tinkoff", "GAZP", 3001, AssetCategory.EQUITIES, "sleeve-equity")
        profile = _profile_for_venue(AssetCategory.EQUITIES)
        sleeve = _sleeve_for(AssetCategory.EQUITIES, "sleeve-equity")
        pipeline = ValidationPipeline(profile, sleeve)

        report = await run_validation_on_bars(
            pipeline,
            bars,
            venue=venue,
            strategy=Strategy.MEAN_REVERSION,
            period_days=PERIOD_DAYS,
            used_stub_data=stub,
        )

        assert report.source == "tinkoff"
        assert report.period_days == PERIOD_DAYS
        if stub:
            assert report.used_stub_data is True

    @pytest.mark.asyncio
    async def test_combined_90_day_all_sources(self):
        binance_bars, binance_stub = await fetch_binance_bars("BTC-USD", days=PERIOD_DAYS)
        if len(binance_bars) < 30:
            binance_bars = generate_synthetic_bars("BTC-USD", days=PERIOD_DAYS, seed=7)
            binance_stub = True

        moex_bars, moex_stub = await fetch_moex_bars("SBER", days=PERIOD_DAYS)
        tinkoff_bars, tinkoff_stub = fetch_tinkoff_bars("GAZP", days=PERIOD_DAYS)

        venues = {
            "binance": VenueConfig("binance", "BTC-USD", 1001, AssetCategory.CRYPTO, "sleeve-crypto"),
            "moex": VenueConfig("moex", "SBER", 2001, AssetCategory.EQUITIES, "sleeve-equity"),
            "tinkoff": VenueConfig("tinkoff", "GAZP", 3001, AssetCategory.EQUITIES, "sleeve-equity"),
        }
        venue_bars = {
            "binance": (binance_bars, binance_stub),
            "moex": (moex_bars, moex_stub),
            "tinkoff": (tinkoff_bars, tinkoff_stub),
        }

        profile = _profile_for_venue(AssetCategory.CRYPTO)
        sleeve = _sleeve_for(AssetCategory.CRYPTO, "sleeve-crypto")
        pipeline = ValidationPipeline(profile, sleeve)

        combined = await run_combined_validation(
            pipeline,
            venue_bars,
            venues=venues,
            strategies=STRATEGIES,
            period_days=PERIOD_DAYS,
        )

        assert len(combined.reports) == len(STRATEGIES) * 3
        summary = combined.summary()
        assert summary["period_days"] == PERIOD_DAYS
        assert len(combined.gaps) >= len(KNOWN_GAPS)
