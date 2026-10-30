"""Tests for enhanced forecast output fields."""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.forecast.types import ForecastDirection, ForecastSignals
from app.services.prediction_hierarchy.action_forecast import ActionForecastContext, ActionForecastEngine
from app.services.prediction_hierarchy.forecast_output import (
    ForecastOutputBuilder,
    ForecastSourceBundle,
    _dedupe_risk_items,
    _narrative_scenario_probabilities,
)
from app.services.prediction_hierarchy.global_regime import GlobalMacroRegimeEngine, MacroIndicatorSnapshot
from app.services.prediction_hierarchy.narrator import PredictionNarrator
from app.services.prediction_hierarchy.types import (
    ActionForecast,
    ActionRecommendation,
    ForecastOutput,
    PointForecast,
    PointMagnitudeClass,
)
from app.services.regime.types import RegimeClassificationResult
from app.services.forecast.aggregation import aggregate_forecast
from app.services.forecast.market_forecast import _build_market_outlook_points


def _make_forecast(confidence: float = 0.8):
    signals = ForecastSignals(
        short_term_momentum=0.6,
        momentum_direction=ForecastDirection.BULLISH,
        tail_risk_score=0.2,
        volatility_expansion_probability=0.2,
        correlation_shift_score=0.1,
        liquidity_deterioration_score=0.45,
        event_impact_score=0.1,
    )
    regime = RegimeClassificationResult(
        distribution={"bullish_trend": 0.7, "choppy_range": 0.3},
        dominant_regime="bullish_trend",
        confidence=confidence,
    )
    return aggregate_forecast(
        instrument_id=1,
        regime_distribution=regime.distribution,
        regime_confidence=regime.confidence,
        signals=signals,
    )


class TestEnhancedForecastOutput:
    def test_layers_include_plain_language_summary(self):
        builder = ForecastOutputBuilder()
        forecast = _make_forecast()
        bundle = ForecastSourceBundle(
            instrument_id=1,
            symbol="META",
            as_of="2026-07-18T00:00:00Z",
            prices=[100.0 + i * 0.3 for i in range(60)],
            ticker_forecast=forecast,
            action_forecast=ActionForecast(
                recommendation=ActionRecommendation.HOLD,
                reason="test",
                rule_id="hold",
            ),
            calibrated_confidence=0.75,
        )
        output = builder.build(bundle)
        assert output.point_forecast.plain_language_summary
        assert "META" in output.point_forecast.plain_language_summary
        assert output.interval_forecast.plain_language_summary
        assert output.distribution_forecast.plain_language_summary
        assert output.risk_forecast.plain_language_summary

    def test_scenario_narratives_include_four_types(self):
        builder = ForecastOutputBuilder()
        forecast = _make_forecast()
        bundle = ForecastSourceBundle(
            instrument_id=1,
            symbol="META",
            as_of="2026-07-18T00:00:00Z",
            prices=[100.0 + i * 0.3 for i in range(60)],
            ticker_forecast=forecast,
            action_forecast=ActionForecast(
                recommendation=ActionRecommendation.HOLD,
                reason="test",
                rule_id="hold",
            ),
        )
        output = builder.build(bundle)
        narrative = [
            s
            for s in output.scenario_forecast.scenarios
            if s.scenario_type in {"pessimistic", "realistic", "optimistic", "classic"}
        ]
        types = {s.scenario_type for s in narrative}
        assert types == {"pessimistic", "realistic", "optimistic", "classic"}
        total_prob = sum(s.probability for s in narrative)
        assert total_prob == pytest.approx(1.0, abs=0.01)
        for item in narrative:
            assert item.impact_narrative_ru

    def test_narrative_probabilities_differ_by_symbol_signals(self):
        builder = ForecastOutputBuilder()

        def build(symbol: str, momentum: float, vol: float):
            signals = ForecastSignals(
                short_term_momentum=momentum,
                momentum_direction=ForecastDirection.BULLISH if momentum >= 0.5 else ForecastDirection.BEARISH,
                tail_risk_score=0.15 + vol * 0.3,
                volatility_expansion_probability=vol,
                correlation_shift_score=0.1,
                liquidity_deterioration_score=0.2,
                event_impact_score=0.1,
            )
            forecast = aggregate_forecast(
                instrument_id=1,
                regime_distribution={
                    "bullish_trend": momentum,
                    "choppy_range": max(0.0, 1.0 - momentum),
                },
                regime_confidence=0.7,
                signals=signals,
            )
            bundle = ForecastSourceBundle(
                instrument_id=1,
                symbol=symbol,
                as_of="2026-07-18T00:00:00Z",
                prices=[100.0 + i * (momentum - 0.5) for i in range(60)],
                ticker_forecast=forecast,
                action_forecast=ActionForecast(
                    recommendation=ActionRecommendation.HOLD,
                    reason="test",
                    rule_id="hold",
                ),
            )
            output = builder.build(bundle)
            return {
                s.scenario_type: s.probability
                for s in output.scenario_forecast.scenarios
                if s.scenario_type in {"pessimistic", "realistic", "optimistic", "classic"}
            }

        bullish = build("AAPL", momentum=0.72, vol=0.12)
        bearish = build("XYZ", momentum=0.32, vol=0.58)
        assert bullish["optimistic"] > bearish["optimistic"]
        assert bearish["pessimistic"] > bullish["pessimistic"]
        assert bullish != bearish

    def test_narrative_probability_helper_sums_to_one(self):
        probs = _narrative_scenario_probabilities(
            vol=0.35,
            momentum=0.62,
            tail_risk=0.25,
            composite_risk=0.4,
            regime_distribution={"bullish_trend": 0.6, "choppy_range": 0.4},
        )
        assert set(probs) == {"pessimistic", "realistic", "optimistic", "classic"}
        assert sum(probs.values()) == pytest.approx(1.0, abs=0.001)

    def test_risk_items_deduplicated(self):
        metrics = {
            "liquidity_risk_score": 0.55,
            "liquidity_deterioration_score": 0.60,
            "tail_risk_score": 0.35,
        }
        items = _dedupe_risk_items(metrics)
        metric_names = [item.metric for item in items]
        assert "liquidity_risk_score" in metric_names
        assert "liquidity_deterioration_score" not in metric_names
        assert len(items) == len(set(item.metric for item in items))

    def test_to_dict_includes_explainability_fields(self):
        builder = ForecastOutputBuilder()
        forecast = _make_forecast()
        bundle = ForecastSourceBundle(
            instrument_id=1,
            symbol="META",
            as_of="2026-07-18T00:00:00Z",
            prices=[100.0 + i * 0.3 for i in range(60)],
            ticker_forecast=forecast,
            action_forecast=ActionForecast(
                recommendation=ActionRecommendation.HOLD,
                reason="test",
                rule_id="hold",
            ),
            calibrated_confidence=0.75,
        )
        output = builder.build(bundle)
        narrator = PredictionNarrator()
        insights = narrator.narrate(output)
        enriched = replace(
            output,
            instruction_block=narrator.build_instruction_block(output, insights),
            basis_block=narrator.build_basis_block(output, ticker_forecast=forecast),
            narrator_insights=insights,
        )
        payload = enriched.to_dict()
        assert payload["instruction_block"]
        assert len(payload["basis_block"]) >= 5
        assert payload["risk_engine_report"]["engine"] == "RiskEngine"
        assert "engines_used" in payload["prediction_system_report"]
        assert payload["prediction_system_report"]["general_summary"]
        assert "Наиболее вероятный сценарий" in payload["prediction_system_report"]["general_summary"]
        assert payload["point_forecast"]["plain_language_summary"]
        assert payload["risk_forecast"]["risk_items"] is not None


class TestPredictionNarratorEnhanced:
    def test_instruction_and_basis_blocks(self):
        builder = ForecastOutputBuilder()
        forecast = _make_forecast()
        bundle = ForecastSourceBundle(
            instrument_id=1,
            symbol="AAPL",
            as_of="2026-07-18",
            prices=[100.0 + i * 0.2 for i in range(60)],
            ticker_forecast=forecast,
            action_forecast=ActionForecast(
                recommendation=ActionRecommendation.HOLD,
                reason="Moderate risk",
                rule_id="hold",
            ),
            calibrated_confidence=0.65,
        )
        output = builder.build(bundle)
        narrator = PredictionNarrator()
        insights = narrator.narrate(output)
        instruction = narrator.build_instruction_block(output, insights)
        basis = narrator.build_basis_block(output, ticker_forecast=forecast)
        assert "AAPL" in instruction
        assert any(block.layer == "point" for block in basis)
        assert any(block.engine == "RiskEngine" for block in basis)


class TestMarketOutlookPoints:
    def test_builds_exactly_three_detailed_points(self):
        engine = GlobalMacroRegimeEngine()
        global_result = engine.classify(MacroIndicatorSnapshot(vix=22.0, cpi=3.2, rate_cb=5.25))
        points = _build_market_outlook_points(
            global_result,
            {"vix": 22.0, "cpi": 3.2, "rate_cb": 5.25},
            [],
        )
        assert len(points) == 3
        for point in points:
            assert point["title"]
            assert point["what_happens"]
            assert point["how"]
            assert point["where"]
            assert point["expectations"]
            assert point["prognosis"]
            assert point["evidence_basis"]
            assert point["confidence_pct"] > 0


class TestFomcCalendar:
    def test_next_fomc_window_after_july_2026(self):
        from datetime import datetime, timezone

        from app.services.macro.fomc_calendar import next_fomc_window

        window = next_fomc_window(datetime(2026, 7, 18, tzinfo=timezone.utc))
        assert window is not None
        assert window["source"] == "fomc_calendar"
        scheduled = window["scheduled_at"]
        assert isinstance(scheduled, datetime)
        assert scheduled.date() >= datetime(2026, 7, 18).date()
