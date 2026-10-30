"""ForecastEngine domain types (Prompt 22).

This module models a probabilistic risk/regime map — not a price forecast.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.services.regime.types import RegimeClassificationResult


class ForecastDirection(StrEnum):
    """Directional read on a contributing factor."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    RISK_UP = "risk_up"
    RISK_DOWN = "risk_down"
    NEUTRAL = "neutral"


class RiskFlag(StrEnum):
    """Explicit risk flags surfaced by the ensemble."""

    TAIL_RISK = "tail_risk"
    VOLATILITY_EXPANSION = "volatility_expansion"
    CORRELATION_SHIFT = "correlation_shift"
    LIQUIDITY_DETERIORATION = "liquidity_deterioration"
    EVENT_IMPACT = "event_impact"
    ELEVATED_UNCERTAINTY = "elevated_uncertainty"


RISK_SIGNAL_FACTORS: tuple[str, ...] = (
    "tail_risk_score",
    "volatility_expansion_probability",
    "correlation_shift_score",
    "liquidity_deterioration_score",
    "event_impact_score",
)


@dataclass(frozen=True, slots=True)
class ContributingFactor:
    """One weighted factor in the ensemble output."""

    factor: str
    weight: float
    direction: ForecastDirection


@dataclass(frozen=True, slots=True)
class ForecastSignals:
    """Normalized signal scores in [0, 1] used by aggregation."""

    short_term_momentum: float
    momentum_direction: ForecastDirection
    tail_risk_score: float
    volatility_expansion_probability: float
    correlation_shift_score: float
    liquidity_deterioration_score: float
    event_impact_score: float

    def as_dict(self) -> dict[str, float]:
        return {
            "short_term_momentum": self.short_term_momentum,
            "tail_risk_score": self.tail_risk_score,
            "volatility_expansion_probability": self.volatility_expansion_probability,
            "correlation_shift_score": self.correlation_shift_score,
            "liquidity_deterioration_score": self.liquidity_deterioration_score,
            "event_impact_score": self.event_impact_score,
        }


@dataclass(frozen=True, slots=True)
class InstrumentForecast:
    """Probabilistic per-instrument map — not a price prediction."""

    instrument_id: int
    regime_distribution: dict[str, float]
    risk_flags: tuple[str, ...]
    confidence: float
    contributing_factors: tuple[ContributingFactor, ...]
    composite_risk_score: float
    signals: ForecastSignals
    dominant_regime: str

    def validate(self) -> None:
        if not self.regime_distribution:
            raise ValueError("regime_distribution must not be empty")
        total = sum(self.regime_distribution.values())
        if not (0.999 <= total <= 1.001):
            raise ValueError(f"regime_distribution must sum to 1.0, got {total}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")
        if not (0.0 <= self.composite_risk_score <= 1.0):
            raise ValueError("composite_risk_score must be in [0, 1]")
        if self.dominant_regime not in self.regime_distribution:
            raise ValueError("dominant_regime must appear in regime_distribution")

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "regime_distribution": dict(self.regime_distribution),
            "risk_flags": list(self.risk_flags),
            "confidence": self.confidence,
            "contributing_factors": [
                {
                    "factor": item.factor,
                    "weight": item.weight,
                    "direction": item.direction.value,
                }
                for item in self.contributing_factors
            ],
            "composite_risk_score": self.composite_risk_score,
            "dominant_regime": self.dominant_regime,
            "signals": self.signals.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class ForecastInputBundle:
    """Inputs for pure or DB-backed forecast computation."""

    instrument_id: int
    prices: list[float]
    volumes: list[float] | None = None
    spread_bps: float | None = None
    returns: list[float] | None = None
    regime_result: RegimeClassificationResult | None = None
    correlation_edge_weights: list[float] | None = None
    prior_correlation_edge_weights: list[float] | None = None
    liquidity_score: float | None = None
    prior_liquidity_score: float | None = None
    depth_ratio: float | None = None
    prior_depth_ratio: float | None = None
    prior_spread_bps: float | None = None
    event_impact_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
