"""Ensemble aggregation for ForecastEngine (Prompt 22).

Uses max-pooled risk aggregation so tail signals are not averaged away by neutral inputs.
"""
from __future__ import annotations

from app.services.forecast.types import (
    ContributingFactor,
    ForecastDirection,
    ForecastSignals,
    InstrumentForecast,
    RISK_SIGNAL_FACTORS,
    RiskFlag,
)
from app.services.regime.types import ALL_REGIME_LABELS, MarketRegimeLabel


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def composite_risk_score(signals: ForecastSignals) -> float:
    """Max-pooled composite so a single elevated tail signal dominates."""
    risk_values = [
        signals.tail_risk_score,
        signals.volatility_expansion_probability,
        signals.correlation_shift_score,
        signals.liquidity_deterioration_score,
        signals.event_impact_score,
    ]
    peak = max(risk_values)
    average = sum(risk_values) / len(risk_values)
    return _clamp(peak * 0.65 + average * 0.35)


def build_risk_flags(
    signals: ForecastSignals,
    *,
    composite_risk: float,
    risk_flag_threshold: float,
    elevated_uncertainty_threshold: float,
) -> tuple[str, ...]:
    flags: list[str] = []
    if signals.tail_risk_score >= risk_flag_threshold:
        flags.append(RiskFlag.TAIL_RISK.value)
    if signals.volatility_expansion_probability >= risk_flag_threshold:
        flags.append(RiskFlag.VOLATILITY_EXPANSION.value)
    if signals.correlation_shift_score >= risk_flag_threshold:
        flags.append(RiskFlag.CORRELATION_SHIFT.value)
    if signals.liquidity_deterioration_score >= risk_flag_threshold:
        flags.append(RiskFlag.LIQUIDITY_DETERIORATION.value)
    if signals.event_impact_score >= risk_flag_threshold:
        flags.append(RiskFlag.EVENT_IMPACT.value)
    if composite_risk >= elevated_uncertainty_threshold and RiskFlag.ELEVATED_UNCERTAINTY.value not in flags:
        flags.append(RiskFlag.ELEVATED_UNCERTAINTY.value)
    return tuple(flags)


def _regime_direction(label: str) -> ForecastDirection:
    if label in {
        MarketRegimeLabel.BULLISH_TREND.value,
    }:
        return ForecastDirection.BULLISH
    if label in {
        MarketRegimeLabel.BEARISH_TREND.value,
    }:
        return ForecastDirection.BEARISH
    if label in {
        MarketRegimeLabel.HIGH_VOLATILITY_SHOCK.value,
        MarketRegimeLabel.LIQUIDITY_DROUGHT.value,
        MarketRegimeLabel.MACRO_UNCERTAINTY.value,
    }:
        return ForecastDirection.RISK_UP
    return ForecastDirection.NEUTRAL


def build_contributing_factors(
    signals: ForecastSignals,
    *,
    regime_distribution: dict[str, float],
) -> tuple[ContributingFactor, ...]:
    regime_weight = 0.30
    momentum_weight = 0.10
    per_risk_weight = 0.12

    dominant_regime = max(regime_distribution, key=regime_distribution.get)
    factors: list[ContributingFactor] = [
        ContributingFactor(
            factor="short_term_momentum",
            weight=momentum_weight,
            direction=signals.momentum_direction,
        ),
        ContributingFactor(
            factor="medium_term_regime_probability",
            weight=regime_weight,
            direction=_regime_direction(dominant_regime),
        ),
    ]

    risk_direction = ForecastDirection.RISK_UP
    for factor_name in RISK_SIGNAL_FACTORS:
        score = signals.as_dict()[factor_name]
        direction = ForecastDirection.NEUTRAL if score < 0.2 else risk_direction
        factors.append(
            ContributingFactor(
                factor=factor_name,
                weight=per_risk_weight,
                direction=direction,
            )
        )
    return tuple(factors)


def compute_confidence(
    *,
    regime_confidence: float,
    regime_distribution: dict[str, float],
    composite_risk: float,
    peak_risk: float,
) -> float:
    """Confidence drops when risk is elevated or regime probabilities are diffuse."""
    dominant_prob = max(regime_distribution.values())
    entropy_penalty = 1.0 - dominant_prob
    risk_penalty = composite_risk * 0.55 + peak_risk * 0.25
    confidence = regime_confidence * (1.0 - risk_penalty) * (1.0 - entropy_penalty * 0.35)
    return _clamp(confidence)


def aggregate_forecast(
    *,
    instrument_id: int,
    regime_distribution: dict[str, float],
    regime_confidence: float,
    signals: ForecastSignals,
    risk_flag_threshold: float = 0.45,
    elevated_uncertainty_threshold: float = 0.50,
) -> InstrumentForecast:
    """Combine signals into a probabilistic map (not a price prediction)."""
    normalized_distribution = {label.value: 0.0 for label in ALL_REGIME_LABELS}
    for label, probability in regime_distribution.items():
        if label in normalized_distribution:
            normalized_distribution[label] = float(probability)

    total = sum(normalized_distribution.values())
    if total <= 0:
        normalized_distribution[MarketRegimeLabel.CHOPPY_RANGE.value] = 1.0
        total = 1.0
    normalized_distribution = {
        label: value / total for label, value in normalized_distribution.items()
    }

    composite_risk = composite_risk_score(signals)
    peak_risk = max(
        signals.tail_risk_score,
        signals.volatility_expansion_probability,
        signals.correlation_shift_score,
        signals.liquidity_deterioration_score,
        signals.event_impact_score,
    )
    risk_flags = build_risk_flags(
        signals,
        composite_risk=composite_risk,
        risk_flag_threshold=risk_flag_threshold,
        elevated_uncertainty_threshold=elevated_uncertainty_threshold,
    )
    confidence = compute_confidence(
        regime_confidence=regime_confidence,
        regime_distribution=normalized_distribution,
        composite_risk=composite_risk,
        peak_risk=peak_risk,
    )
    dominant_regime = max(normalized_distribution, key=normalized_distribution.get)
    forecast = InstrumentForecast(
        instrument_id=instrument_id,
        regime_distribution=normalized_distribution,
        risk_flags=risk_flags,
        confidence=confidence,
        contributing_factors=build_contributing_factors(
            signals,
            regime_distribution=normalized_distribution,
        ),
        composite_risk_score=composite_risk,
        signals=signals,
        dominant_regime=dominant_regime,
    )
    forecast.validate()
    return forecast
