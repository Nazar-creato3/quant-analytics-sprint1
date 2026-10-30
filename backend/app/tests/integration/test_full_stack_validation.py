"""Prompt 30 — full stack integration & validation end-to-end tests."""
from __future__ import annotations

import pytest

from app.domain.enums import AssetCategory, Strategy
from app.services.integration.full_stack_validation import (
    compute_risk_gate_accuracy,
    run_full_stack_validation,
)
from app.services.integration.historical_data import generate_synthetic_bars
from app.services.integration.pipeline import ValidationPipeline, run_validation_on_bars
from app.services.integration.stack import PredictionRiskStack
from app.services.integration.types import VenueConfig
from app.tests.integration.test_historical_replay_validation import (
    PERIOD_DAYS,
    _profile_for_venue,
    _sleeve_for,
)


@pytest.mark.integration
class TestPredictionRiskStack:
    def test_stack_wires_all_modules(self, validation_profile, crypto_sleeve, binance_venue):
        bars = generate_synthetic_bars("BTC-USD", days=90, seed=11)
        stack = PredictionRiskStack()
        context = stack.build_at_index(
            {binance_venue.instrument_id: bars},
            target=binance_venue,
            index=40,
            profile=validation_profile,
            sleeve=crypto_sleeve,
        )

        assert context.regime_result.dominant_regime
        assert context.forecast.confidence >= 0.0
        assert context.market_context.dominant_regime == context.regime_result.dominant_regime
        assert context.market_context.forecast_composite_risk_score == pytest.approx(
            context.forecast.composite_risk_score
        )
        assert context.risk_inputs.instrument_id == binance_venue.instrument_id
        assert context.correlation_edges is not None


@pytest.mark.integration
class TestFullStackValidation:
    @pytest.mark.asyncio
    async def test_full_stack_validation_report(self):
        venues = {
            "binance": VenueConfig(
                "binance",
                "BTC-USD",
                1001,
                AssetCategory.CRYPTO,
                "sleeve-crypto",
            ),
            "moex": VenueConfig(
                "moex",
                "SBER",
                2001,
                AssetCategory.EQUITIES,
                "sleeve-equity",
            ),
            "tinkoff": VenueConfig(
                "tinkoff",
                "GAZP",
                3001,
                AssetCategory.EQUITIES,
                "sleeve-equity",
            ),
        }
        venue_bars = {
            "binance": (generate_synthetic_bars("BTC-USD", days=PERIOD_DAYS, seed=1), True),
            "moex": (generate_synthetic_bars("SBER", days=PERIOD_DAYS, seed=2), True),
            "tinkoff": (generate_synthetic_bars("GAZP", days=PERIOD_DAYS, seed=3), True),
        }
        profile = _profile_for_venue(AssetCategory.CRYPTO)
        sleeves = {
            "sleeve-crypto": _sleeve_for(AssetCategory.CRYPTO, "sleeve-crypto"),
            "sleeve-equity": _sleeve_for(AssetCategory.EQUITIES, "sleeve-equity"),
        }
        pipeline = ValidationPipeline(profile, sleeves["sleeve-crypto"])

        report = await run_full_stack_validation(
            profile,
            sleeves,
            venues,
            venue_bars,
            pipeline=pipeline,
            period_days=PERIOD_DAYS,
            strategies=[Strategy.GRID, Strategy.TREND],
        )

        summary = report.summary()
        assert report.period_days == PERIOD_DAYS
        assert len(report.modules_connected) >= 10
        assert len(report.deal_intent_report.reports) == 6
        assert len(report.prediction_replay_by_venue) == 3
        assert report.risk_gate_metrics.total_decisions > 0
        assert 0.0 <= report.risk_gate_metrics.false_positive_rate <= 1.0
        assert 0.0 <= report.risk_gate_metrics.false_negative_rate <= 1.0
        assert report.stress_report.profile_id == profile.id
        assert report.stress_report.scenario_results

        for source, replay in report.prediction_replay_by_venue.items():
            assert replay.total_points > 0
            assert 0.0 <= replay.regime_accuracy <= 1.0
            assert source in venues

        assert "prediction_replay" in summary
        assert "risk_gate_metrics" in summary
        assert "stress_harness" in summary

    @pytest.mark.asyncio
    async def test_pipeline_uses_prediction_stack_context(
        self,
        validation_profile,
        crypto_sleeve,
        binance_venue,
    ):
        bars = generate_synthetic_bars("BTC-USD", days=90, seed=21)
        stack = PredictionRiskStack()
        pipeline = ValidationPipeline(
            validation_profile,
            crypto_sleeve,
            prediction_stack=stack,
        )

        report = await run_validation_on_bars(
            pipeline,
            bars,
            venue=binance_venue,
            strategy=Strategy.GRID,
            period_days=90,
            stack=stack,
            bars_by_instrument={binance_venue.instrument_id: bars},
        )

        assert report.total_bars == 90
        assert report.intents_proposed >= 0

    def test_risk_gate_accuracy_metrics(self, validation_profile, crypto_sleeve):
        venues = {
            "binance": VenueConfig(
                "binance",
                "BTC-USD",
                1001,
                AssetCategory.CRYPTO,
                "sleeve-crypto",
            ),
        }
        bars = generate_synthetic_bars("BTC-USD", days=90, seed=31)
        bars_by_instrument = {1001: bars}

        metrics = compute_risk_gate_accuracy(
            bars_by_instrument,
            venues,
            profile=validation_profile,
            sleeve=crypto_sleeve,
        )

        assert metrics.total_decisions > 0
        assert metrics.blocked_count + metrics.allowed_count == metrics.total_decisions
        assert (
            metrics.false_positive_count
            + metrics.true_positive_count
            == metrics.blocked_count
        )
        assert (
            metrics.false_negative_count
            + metrics.true_negative_count
            == metrics.allowed_count
        )
