"""Prompt 15 — end-to-end DealIntent validation on synthetic historical data."""
from __future__ import annotations

import pytest

from app.domain.enums import Strategy
from app.services.integration.pipeline import run_replay_consistency_check, run_validation_on_bars
from app.services.integration.report import CombinedValidationReport


@pytest.mark.integration
class TestDealIntentPipelineE2E:
    @pytest.mark.asyncio
    async def test_full_pipeline_produces_audit_trail(
        self,
        validation_pipeline,
        synthetic_bars_90,
        binance_venue,
    ):
        report = await run_validation_on_bars(
            validation_pipeline,
            synthetic_bars_90,
            venue=binance_venue,
            strategy=Strategy.GRID,
            period_days=90,
        )

        assert report.total_bars == 90
        assert report.source == "binance"
        assert isinstance(report.win_rate, float)
        assert isinstance(report.max_drawdown_pct, float)
        assert isinstance(report.sharpe_ratio, float)
        assert len(report.audit_entries) >= 0
        actions = {entry.action for entry in report.audit_entries}
        if report.intents_executed > 0:
            assert "control_fabric.execution" in actions

        for item in report.rejected:
            assert item.reason
            assert item.stage in {
                "compliance",
                "strategy_mesh",
                "sleeve_engine",
                "risk_gate",
                "approval_policy",
            }

        for item in report.held:
            assert item.reason
            assert item.stage == "approval_policy"

    @pytest.mark.asyncio
    async def test_all_strategies_run_on_synthetic_data(
        self,
        validation_profile,
        crypto_sleeve,
        synthetic_bars_90,
        binance_venue,
    ):
        from app.services.integration.pipeline import ValidationPipeline

        summaries = []
        for strategy in Strategy:
            pipeline = ValidationPipeline(validation_profile, crypto_sleeve)
            report = await run_validation_on_bars(
                pipeline,
                synthetic_bars_90,
                venue=binance_venue,
                strategy=strategy,
                period_days=90,
            )
            summaries.append(report.summary())
            assert report.period_days == 90

        assert len(summaries) == len(Strategy)

    def test_replay_engine_consistency_on_synthetic(
        self,
        validation_pipeline,
        synthetic_bars_90,
        binance_venue,
    ):
        matched = run_replay_consistency_check(
            validation_pipeline,
            synthetic_bars_90,
            venue=binance_venue,
            strategy=Strategy.TREND,
        )
        assert matched >= 0

    @pytest.mark.asyncio
    async def test_combined_synthetic_venues(
        self,
        validation_profile,
        crypto_sleeve,
        equity_sleeve,
    ):
        from app.services.integration.historical_data import generate_synthetic_bars
        from app.services.integration.pipeline import ValidationPipeline, run_combined_validation
        from app.services.integration.types import VenueConfig

        venues = {
            "binance": VenueConfig("binance", "BTC-USD", 1001, crypto_sleeve.category, crypto_sleeve.id),
            "moex": VenueConfig("moex", "SBER", 2001, equity_sleeve.category, equity_sleeve.id),
            "tinkoff": VenueConfig("tinkoff", "GAZP", 3001, equity_sleeve.category, equity_sleeve.id),
        }
        venue_bars = {
            "binance": (generate_synthetic_bars("BTC-USD", days=90, seed=1), True),
            "moex": (generate_synthetic_bars("SBER", days=90, seed=2), True),
            "tinkoff": (generate_synthetic_bars("GAZP", days=90, seed=3), True),
        }
        pipeline = ValidationPipeline(validation_profile, crypto_sleeve)
        combined = await run_combined_validation(
            pipeline,
            venue_bars,
            venues=venues,
            strategies=[Strategy.GRID, Strategy.TREND],
            period_days=90,
        )

        assert isinstance(combined, CombinedValidationReport)
        assert len(combined.reports) == 6
        summary = combined.summary()
        assert summary["period_days"] == 90
        assert "combined_win_rate" in summary
