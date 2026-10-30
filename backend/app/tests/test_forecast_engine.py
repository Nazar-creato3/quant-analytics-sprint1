"""Tests for Prompt 22 ForecastEngine probabilistic ensemble."""
from __future__ import annotations

import math

import pytest

from app.services.forecast import (
    ForecastDirection,
    ForecastEngine,
    ForecastInputBundle,
    ForecastSignals,
    RiskFlag,
    aggregate_forecast,
    composite_risk_score,
    compute_liquidity_deterioration_score,
)
from app.services.regime import MarketRegimeLabel, RegimeEngine
from app.services.regime.types import RegimeClassificationResult


def _neutral_regime() -> RegimeClassificationResult:
    distribution = {label.value: 0.0 for label in MarketRegimeLabel}
    distribution[MarketRegimeLabel.CHOPPY_RANGE.value] = 0.55
    distribution[MarketRegimeLabel.BULLISH_TREND.value] = 0.25
    distribution[MarketRegimeLabel.BEARISH_TREND.value] = 0.20
    return RegimeClassificationResult(
        distribution=distribution,
        dominant_regime=MarketRegimeLabel.CHOPPY_RANGE.value,
        confidence=0.82,
    )


def _flat_prices(count: int = 40, start: float = 100.0) -> list[float]:
    return [start + math.sin(index * 0.15) * 0.05 for index in range(count)]


class TestForecastSignals:
    def test_liquidity_deterioration_detects_spread_and_depth_collapse(self):
        score = compute_liquidity_deterioration_score(
            liquidity_score=0.15,
            prior_liquidity_score=0.85,
            spread_bps=85.0,
            prior_spread_bps=8.0,
            depth_ratio=0.12,
            prior_depth_ratio=0.95,
        )
        assert score >= 0.75

    def test_composite_risk_max_pools_tail_signal(self):
        neutral = ForecastSignals(
            short_term_momentum=0.1,
            momentum_direction=ForecastDirection.NEUTRAL,
            tail_risk_score=0.1,
            volatility_expansion_probability=0.1,
            correlation_shift_score=0.1,
            liquidity_deterioration_score=0.1,
            event_impact_score=0.1,
        )
        stressed = ForecastSignals(
            short_term_momentum=0.1,
            momentum_direction=ForecastDirection.NEUTRAL,
            tail_risk_score=0.1,
            volatility_expansion_probability=0.1,
            correlation_shift_score=0.1,
            liquidity_deterioration_score=0.92,
            event_impact_score=0.1,
        )
        assert composite_risk_score(stressed) > composite_risk_score(neutral) + 0.35


class TestForecastAggregation:
    def test_all_neutral_signals_low_risk_high_confidence(self):
        signals = ForecastSignals(
            short_term_momentum=0.08,
            momentum_direction=ForecastDirection.NEUTRAL,
            tail_risk_score=0.07,
            volatility_expansion_probability=0.06,
            correlation_shift_score=0.05,
            liquidity_deterioration_score=0.05,
            event_impact_score=0.04,
        )
        forecast = aggregate_forecast(
            instrument_id=101,
            regime_distribution=_neutral_regime().distribution,
            regime_confidence=0.85,
            signals=signals,
        )
        assert forecast.composite_risk_score < 0.2
        assert forecast.confidence >= 0.55
        assert forecast.risk_flags == ()
        assert forecast.dominant_regime == MarketRegimeLabel.CHOPPY_RANGE.value

    def test_liquidity_spike_not_averaged_away(self):
        neutral_signals = ForecastSignals(
            short_term_momentum=0.08,
            momentum_direction=ForecastDirection.NEUTRAL,
            tail_risk_score=0.08,
            volatility_expansion_probability=0.07,
            correlation_shift_score=0.06,
            liquidity_deterioration_score=0.05,
            event_impact_score=0.05,
        )
        stressed_signals = ForecastSignals(
            short_term_momentum=0.08,
            momentum_direction=ForecastDirection.NEUTRAL,
            tail_risk_score=0.08,
            volatility_expansion_probability=0.07,
            correlation_shift_score=0.06,
            liquidity_deterioration_score=0.93,
            event_impact_score=0.05,
        )
        neutral = aggregate_forecast(
            instrument_id=101,
            regime_distribution=_neutral_regime().distribution,
            regime_confidence=0.85,
            signals=neutral_signals,
        )
        stressed = aggregate_forecast(
            instrument_id=101,
            regime_distribution=_neutral_regime().distribution,
            regime_confidence=0.85,
            signals=stressed_signals,
        )
        assert RiskFlag.LIQUIDITY_DETERIORATION.value in stressed.risk_flags
        assert RiskFlag.ELEVATED_UNCERTAINTY.value in stressed.risk_flags
        assert stressed.composite_risk_score > 0.45
        assert stressed.confidence < neutral.confidence - 0.15
        assert stressed.composite_risk_score > neutral.composite_risk_score + 0.35


class TestForecastEngine:
    def setup_method(self) -> None:
        self.engine = ForecastEngine()
        self.regime_engine = RegimeEngine()

    def test_compute_from_neutral_inputs(self):
        prices = _flat_prices()
        regime = self.regime_engine.classify_instrument(prices, spread_bps=8.0)
        forecast = self.engine.compute_from_inputs(
            ForecastInputBundle(
                instrument_id=42,
                prices=prices,
                spread_bps=8.0,
                regime_result=regime,
                liquidity_score=0.88,
                prior_liquidity_score=0.90,
                depth_ratio=0.95,
                prior_depth_ratio=0.96,
                prior_spread_bps=7.5,
                correlation_edge_weights=[0.25, 0.30, 0.28],
                prior_correlation_edge_weights=[0.26, 0.29, 0.27],
                event_impact_score=0.05,
            )
        )
        forecast.validate()
        assert forecast.instrument_id == 42
        assert pytest.approx(sum(forecast.regime_distribution.values()), rel=1e-6) == 1.0
        assert forecast.composite_risk_score < 0.25
        assert forecast.confidence >= 0.35
        assert len(forecast.contributing_factors) >= 5

    def test_liquidity_deterioration_dominates_neutral_peers(self):
        prices = _flat_prices()
        regime = _neutral_regime()
        forecast = self.engine.compute_from_inputs(
            ForecastInputBundle(
                instrument_id=7,
                prices=prices,
                spread_bps=90.0,
                prior_spread_bps=8.0,
                regime_result=regime,
                liquidity_score=0.12,
                prior_liquidity_score=0.86,
                depth_ratio=0.10,
                prior_depth_ratio=0.92,
                correlation_edge_weights=[0.2, 0.22],
                prior_correlation_edge_weights=[0.21, 0.20],
                event_impact_score=0.06,
            )
        )
        assert RiskFlag.LIQUIDITY_DETERIORATION.value in forecast.risk_flags
        assert forecast.composite_risk_score >= 0.5
        assert forecast.confidence <= 0.45
        liquidity_factor = next(
            item for item in forecast.contributing_factors if item.factor == "liquidity_deterioration_score"
        )
        assert liquidity_factor.direction.value == "risk_up"

    def test_output_is_probability_map_not_price_prediction(self):
        prices = _flat_prices()
        forecast = self.engine.compute_from_inputs(
            ForecastInputBundle(
                instrument_id=1,
                prices=prices,
                regime_result=_neutral_regime(),
            )
        )
        payload = forecast.to_dict()
        assert "regime_distribution" in payload
        assert "risk_flags" in payload
        assert "confidence" in payload
        assert "contributing_factors" in payload
        forbidden_keys = {"predicted_price", "price_target", "expected_price"}
        assert forbidden_keys.isdisjoint(payload.keys())
