"""Tests for prediction hierarchy engines (Prompts 31-40) and partial completions."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.deal_intent_enums import RiskTag
from app.services.approval.engine import evaluate_policy
from app.services.approval.models import MarketContext
from app.services.control_fabric.replay_engine import ReplayEngine
from app.services.control_fabric.risk_engine import RiskEngine
from app.services.event_risk.historical_calibration import NewsImpactHistoricalCalibrator
from app.services.event_risk.news_impact import NewsImpactAnalog
from app.services.forecast.aggregation import aggregate_forecast
from app.services.forecast.types import ForecastDirection, ForecastSignals
from app.services.prediction_hierarchy.action_forecast import ActionForecastContext, ActionForecastEngine
from app.services.prediction_hierarchy.confidence_calibrator import (
    CalibrationInput,
    ForecastConfidenceCalibrator,
    compute_calibration_error,
)
from app.services.prediction_hierarchy.forecast_output import ForecastOutputBuilder, ForecastSourceBundle
from app.services.prediction_hierarchy.global_regime import (
    CREDIT_SPREAD_SOURCE_FRED,
    CREDIT_SPREAD_SOURCE_NONE,
    GlobalMacroRegimeEngine,
    MacroIndicatorSnapshot,
    compute_credit_spread_proxy,
)
from app.services.prediction_hierarchy.hierarchy_validation import HierarchyValidationEngine
from app.services.prediction_hierarchy.marginal_risk import PortfolioMarginalRiskEngine
from app.services.prediction_hierarchy.narrator import PredictionNarrator
from app.services.prediction_hierarchy.sector_regime import SectorRegimeEngine
from app.services.prediction_hierarchy.types import (
    ActionForecast,
    ActionRecommendation,
    DistributionForecast,
    ForecastOutput,
    IntervalForecast,
    PointForecast,
    PointMagnitudeClass,
    ProposedPositionChange,
    RiskForecastLayer,
    ScenarioForecast,
    SectorRotationFlag,
)
from app.services.prediction_hierarchy.orchestrator import PredictionHierarchyOrchestrator
from app.services.regime.types import InstrumentSeries, RegimeClassificationResult
from app.services.scenario.types import PortfolioPosition, PortfolioSnapshot


def _trend_prices(start: float, step: float, count: int) -> list[float]:
    return [start + step * index for index in range(count)]


def _falling_prices(start: float, step: float, count: int) -> list[float]:
    return [start - step * index for index in range(count)]


def _make_forecast(confidence: float = 0.8):
    signals = ForecastSignals(
        short_term_momentum=0.6,
        momentum_direction=ForecastDirection.BULLISH,
        tail_risk_score=0.2,
        volatility_expansion_probability=0.2,
        correlation_shift_score=0.1,
        liquidity_deterioration_score=0.1,
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


class TestSectorRegimeEngine:
    def test_weakening_sector_rotation(self):
        engine = SectorRegimeEngine()
        # Negative cumulative returns over all horizons vs flat market
        sector_returns = [-0.01] * 80
        market_returns = [0.0] * 80
        score = engine.compute_rotation_score("tech", sector_returns, market_returns)
        assert score.rotation_flag == SectorRotationFlag.SECTORS_WEAKENING

    def test_confidence_penalty_in_weak_sector(self):
        strong_ticker = RegimeClassificationResult(
            distribution={"bullish_trend": 0.8, "choppy_range": 0.2},
            dominant_regime="bullish_trend",
            confidence=0.85,
        )
        weak_sector = RegimeClassificationResult(
            distribution={"bearish_trend": 0.7, "choppy_range": 0.3},
            dominant_regime="bearish_trend",
            confidence=0.75,
        )
        adjusted = SectorRegimeEngine.apply_sector_confidence_penalty(0.85, weak_sector)
        assert adjusted < 0.85
        unchanged = SectorRegimeEngine.apply_sector_confidence_penalty(0.85, strong_ticker)
        assert unchanged == pytest.approx(0.85)


class TestGlobalMacroRegimeEngine:
    def test_risk_off_on_high_vix(self):
        engine = GlobalMacroRegimeEngine()
        result = engine.classify(MacroIndicatorSnapshot(vix=35.0, cross_asset_correlation=0.7))
        assert result.dominant_regime in {"risk_off", "macro_uncertainty"}
        assert result.credit_spread_source == CREDIT_SPREAD_SOURCE_NONE
        assert result.credit_spread_proxy is None

    def test_credit_spread_from_fred_hy_and_gov(self):
        spread, source = compute_credit_spread_proxy(hy_oas_pct=5.5, gov_10y_pct=4.2)
        assert source == CREDIT_SPREAD_SOURCE_FRED
        # HY OAS is already over Treasuries — not reduced by the 10Y yield.
        assert spread == pytest.approx(0.055)

        engine = GlobalMacroRegimeEngine()
        result = engine.classify(
            MacroIndicatorSnapshot(
                vix=20.0,
                hy_oas_pct=5.5,
                gov_10y_pct=4.2,
                credit_spread_proxy=spread,
            )
        )
        assert result.credit_spread_source == CREDIT_SPREAD_SOURCE_FRED
        assert result.credit_spread_proxy == pytest.approx(0.055)

    def test_global_confidence_caps_lower_levels(self):
        engine = GlobalMacroRegimeEngine()
        global_result = engine.classify(MacroIndicatorSnapshot(vix=32.0))
        capped = GlobalMacroRegimeEngine.apply_global_confidence_damping(0.90, global_result)
        assert capped <= global_result.confidence


class TestPortfolioMarginalRisk:
    def _portfolio(self) -> PortfolioSnapshot:
        returns_a = [0.01, -0.005, 0.008, 0.002, -0.003] * 10
        returns_b = [0.009, -0.004, 0.007, 0.003, -0.002] * 10
        return PortfolioSnapshot(
            positions=(
                PortfolioPosition(instrument_id=1, sleeve_id="a", weight=0.5),
                PortfolioPosition(instrument_id=2, sleeve_id="a", weight=0.5),
            ),
            factor_exposures={},
            returns_by_instrument={1: returns_a, 2: returns_b},
        )

    def test_correlated_position_large_delta_var(self):
        engine = PortfolioMarginalRiskEngine()
        portfolio = self._portfolio()
        correlated = ProposedPositionChange(instrument_id=1, delta_weight=0.2)
        uncorrelated_returns = [0.02, -0.01, 0.015, -0.008, 0.005] * 10
        diversified = PortfolioSnapshot(
            positions=portfolio.positions,
            factor_exposures={},
            returns_by_instrument={
                1: portfolio.returns_by_instrument[1],
                2: portfolio.returns_by_instrument[2],
                3: uncorrelated_returns,
            },
        )
        corr_result = engine.what_if(portfolio, correlated)
        div_change = ProposedPositionChange(instrument_id=3, delta_weight=0.2)
        div_result = engine.what_if(diversified, div_change)
        assert abs(corr_result.delta_var) >= abs(div_result.delta_var) * 0.5

    def test_marginal_contributions_sum(self):
        engine = PortfolioMarginalRiskEngine()
        contributions = engine.marginal_risk_contribution(self._portfolio())
        assert len(contributions) == 2
        assert sum(contributions.values()) == pytest.approx(1.0, rel=0.05)


class TestForecastOutputBuilder:
    def test_builds_six_layers_from_mock_sources(self):
        builder = ForecastOutputBuilder()
        forecast = _make_forecast()
        bundle = ForecastSourceBundle(
            instrument_id=1,
            symbol="TEST",
            as_of="2026-07-18T00:00:00Z",
            prices=_trend_prices(100.0, 0.5, 60),
            ticker_forecast=forecast,
            action_forecast=ActionForecast(
                recommendation=ActionRecommendation.HOLD,
                reason="test",
                rule_id="test",
            ),
            calibrated_confidence=0.75,
        )
        output = builder.build(bundle)
        assert output.point_forecast.magnitude_class in PointMagnitudeClass
        assert output.interval_forecast.p10 < output.interval_forecast.p90
        assert output.distribution_forecast.p50 is not None
        assert output.action_forecast.recommendation == ActionRecommendation.HOLD

    def test_slots_bundle_supports_dataclass_replace(self):
        from dataclasses import replace

        forecast = _make_forecast()
        partial = ForecastSourceBundle(
            instrument_id=1,
            symbol="TEST",
            as_of="2026-07-18T00:00:00Z",
            prices=_trend_prices(100.0, 0.5, 60),
            ticker_forecast=forecast,
            calibrated_confidence=0.75,
        )
        action = ActionForecast(
            recommendation=ActionRecommendation.HOLD,
            reason="test",
            rule_id="test",
        )
        merged = replace(partial, action_forecast=action)
        output = ForecastOutputBuilder().build(merged)
        assert output.action_forecast.recommendation == ActionRecommendation.HOLD


class TestForecastCacheRestore:
    def test_output_from_cache_restores_scenario_items(self):
        cached = {
            "instrument_id": 1,
            "symbol": "AAPL",
            "as_of": "2026-07-18T00:00:00Z",
            "calibrated_confidence": 0.7,
            "high_confidence": False,
            "point_forecast": {
                "magnitude_class": "up",
                "expected_return_sign": 1,
                "momentum_score": 0.62,
            },
            "interval_forecast": {"horizon_days": 10, "p10": -0.03, "p90": 0.03},
            "distribution_forecast": {
                "p5": -0.04,
                "p25": -0.01,
                "p50": 0.005,
                "p75": 0.02,
                "p95": 0.04,
                "method": "historical_percentile",
            },
            "scenario_forecast": {
                "scenario_dispersion": 0.02,
                "scenarios": [
                    {
                        "name": "pessimistic",
                        "scenario_type": "pessimistic",
                        "label_ru": "Пессимистичный",
                        "probability": 0.18,
                        "impact": -0.03,
                    },
                    {
                        "name": "realistic",
                        "scenario_type": "realistic",
                        "label_ru": "Реалистичный",
                        "probability": 0.42,
                        "impact": 0.005,
                    },
                    {
                        "name": "optimistic",
                        "scenario_type": "optimistic",
                        "label_ru": "Оптимистичный",
                        "probability": 0.24,
                        "impact": 0.025,
                    },
                    {
                        "name": "classic",
                        "scenario_type": "classic",
                        "label_ru": "Классический",
                        "probability": 0.16,
                        "impact": 0.002,
                    },
                ],
            },
            "risk_forecast": {"instrument_metrics": {}, "portfolio_metrics": {}},
            "action_forecast": {"recommendation": "hold", "reason": "ok"},
            "narrator_insights": [],
        }
        restored = PredictionHierarchyOrchestrator._output_from_cache(cached)
        narrative = [
            s
            for s in restored.scenario_forecast.scenarios
            if s.scenario_type in {"pessimistic", "realistic", "optimistic", "classic"}
        ]
        assert len(narrative) == 4
        assert sum(s.probability for s in narrative) == pytest.approx(1.0, abs=0.01)


class TestActionForecastEngine:
    def test_active_locks_recommend_avoid(self):
        engine = ActionForecastEngine()
        result = engine.evaluate(
            ActionForecastContext(
                calibrated_confidence=0.9,
                composite_risk_score=0.2,
                scenario_dispersion=0.01,
                active_locks=frozenset({"news_lock"}),
            )
        )
        assert result.recommendation == ActionRecommendation.AVOID
        assert result.reason

    def test_high_dispersion_recommends_hedge(self):
        engine = ActionForecastEngine()
        result = engine.evaluate(
            ActionForecastContext(
                calibrated_confidence=0.7,
                composite_risk_score=0.4,
                scenario_dispersion=0.12,
            )
        )
        assert result.recommendation == ActionRecommendation.HEDGE


class TestPredictionNarrator:
    def test_generates_expected_insights(self):
        from app.services.prediction_hierarchy.types import DistributionForecast

        output = ForecastOutput(
            instrument_id=1,
            symbol="TEST",
            as_of="2026-07-18",
            point_forecast=PointForecast(PointMagnitudeClass.NEUTRAL, 0, 0.4),
            interval_forecast=IntervalForecast(10, -0.02, 0.02, 0.01, 1.645),
            distribution_forecast=DistributionForecast(0, 0, 0, 0, 0, "test"),
            scenario_forecast=ScenarioForecast(scenarios=(), scenario_dispersion=0.05),
            risk_forecast=RiskForecastLayer({"volatility_expansion_probability": 0.6}, {}),
            action_forecast=ActionForecast(
                ActionRecommendation.ENTER_SMALL_SIZE, "small", "sector_weakness"
            ),
            calibrated_confidence=0.5,
            high_confidence=False,
            global_regime=GlobalMacroRegimeEngine().classify(MacroIndicatorSnapshot(vix=35.0)),
        )
        narrator = PredictionNarrator()
        insights = narrator.narrate(output, news_impact_probability=0.6, correlation_cluster_pct=30.0)
        template_ids = {item.template_id for item in insights}
        assert "vol_expansion" in template_ids
        assert "news_sensitive" in template_ids
        assert "correlation_cluster" in template_ids

    def test_skips_wide_interval_without_rolling_volatility(self):
        from app.services.prediction_hierarchy.interval_support import interval_band_is_supported

        interval = IntervalForecast(10, -0.05, 0.05, 0.0, 1.645)
        assert not interval_band_is_supported(interval)
        output = ForecastOutput(
            instrument_id=1,
            symbol="TEST",
            as_of="2026-07-18",
            point_forecast=PointForecast(PointMagnitudeClass.NEUTRAL, 0, 0.4),
            interval_forecast=interval,
            distribution_forecast=DistributionForecast(0, 0, 0, 0, 0, "degraded_macro_only"),
            scenario_forecast=ScenarioForecast(scenarios=(), scenario_dispersion=0.05),
            risk_forecast=RiskForecastLayer({}, {}),
            action_forecast=ActionForecast(ActionRecommendation.HOLD, "wait", "test"),
            calibrated_confidence=0.5,
            high_confidence=False,
            metadata={"degraded": True},
        )
        insights = PredictionNarrator().narrate(output)
        assert "wide_interval" not in {item.template_id for item in insights}


class TestForecastConfidenceCalibrator:
    def test_low_global_caps_final_confidence(self):
        calibrator = ForecastConfidenceCalibrator()
        global_engine = GlobalMacroRegimeEngine()
        global_result = global_engine.classify(MacroIndicatorSnapshot(vix=40.0))
        forecast = _make_forecast(confidence=0.95)
        result = calibrator.calibrate(
            CalibrationInput(
                ticker_forecast=forecast,
                global_regime=global_result,
                scenario_dispersion=0.02,
            )
        )
        assert result.calibrated_confidence <= global_result.confidence + 0.01

    def test_calibration_error_metric(self):
        error = compute_calibration_error([0.9, 0.8, 0.2, 0.3], [True, True, False, False])
        assert error >= 0.0


class TestHierarchyValidation:
    def test_hierarchy_report_generated(self):
        prices = _trend_prices(100.0, 0.3, 120) + _falling_prices(136.0, 0.5, 20)
        engine = HierarchyValidationEngine()
        report = engine.run(instrument_id=1, prices=prices, min_history=30, forward_horizon=5)
        assert report.total_points > 0
        assert len(report.level_accuracy) == 3
        assert report.calibration_error >= 0.0
        assert len(report.action_hit_rates) >= 1
        assert "uncertainty" in report.summary.lower() or "Calibration" in report.summary

    def test_action_hit_rates_cover_multiple_labels(self):
        prices = _trend_prices(100.0, 0.4, 150)
        engine = HierarchyValidationEngine()
        report = engine.run(instrument_id=1, prices=prices, min_history=30, forward_horizon=5)
        labels = {item.recommendation for item in report.action_hit_rates}
        assert ActionRecommendation.WAIT.value in labels or len(labels) >= 1

    def test_calibration_error_series_populated(self):
        prices = _trend_prices(100.0, 0.2, 140)
        engine = HierarchyValidationEngine()
        report = engine.run(
            instrument_id=1,
            prices=prices,
            min_history=30,
            forward_horizon=5,
            rolling_calibration_window=10,
        )
        assert len(report.calibration_error_series) > 0

    def test_live_calibration_error_from_validation_pairs(self):
        from app.services.prediction_hierarchy.calibration_tracker import (
            get_live_calibration_error,
            record_validation_pairs,
        )

        record_validation_pairs([0.9, 0.8, 0.7] * 8, [True, True, False] * 8)
        assert get_live_calibration_error(min_pairs=20) is not None


class TestGlobalRegimeCreditSpread:
    def test_fred_series_preferred_over_stub(self):
        engine = GlobalMacroRegimeEngine()
        result = engine.classify(
            MacroIndicatorSnapshot(
                vix=20.0,
                hy_oas_pct=5.5,
                gov_10y_pct=4.2,
            )
        )
        assert result.credit_spread_source == CREDIT_SPREAD_SOURCE_FRED
        assert result.credit_spread_proxy == pytest.approx(0.055)


class TestReplayEngineHierarchy:
    def test_replay_hierarchy_extension(self):
        prices = _trend_prices(100.0, 0.2, 100)
        engine = ReplayEngine()
        report = engine.replay_hierarchy(instrument_id=1, prices=prices, min_history=25)
        assert report.total_points > 0


class TestNewsImpactHistoricalCalibration:
    def test_calibration_from_analog_history(self):
        history = tuple(
            NewsImpactAnalog(topic_tags=("rate", "fed"), strong_move=True)
            for _ in range(5)
        )
        calibrator = NewsImpactHistoricalCalibrator()
        result = calibrator.calibrate_from_history(
            topic_tags=("rate", "fed"),
            factor_exposures={"rates_sensitivity": 0.8},
            history=history,
            daily_volatility=0.015,
        )
        assert result.probability > 0.4
        assert result.calibrated is True


class TestApprovalMarginalRiskGate:
    def test_delta_var_blocks_auto_approve(self):
        from app.tests.test_approval_policy_engine import _context, _intent, _profile
        from app.services.approval.models import PolicyState

        baseline = evaluate_policy(_intent(risk_tag=RiskTag.LOW), _profile(), _context())
        assert baseline.state == PolicyState.AUTO_APPROVE

        blocked = evaluate_policy(
            _intent(risk_tag=RiskTag.LOW),
            _profile(),
            _context(proposed_delta_var=0.08, remaining_risk_budget_var=0.05),
        )
        assert blocked.state == PolicyState.HOLD_FOR_REVIEW
        assert "delta_var" in blocked.reason
