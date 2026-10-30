"""Types for probabilistic market regime classification."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MarketRegimeLabel(str, Enum):
    """Canonical regime labels returned by RegimeEngine."""

    BULLISH_TREND = "bullish_trend"
    BEARISH_TREND = "bearish_trend"
    CHOPPY_RANGE = "choppy_range"
    HIGH_VOLATILITY_SHOCK = "high_volatility_shock"
    LIQUIDITY_DROUGHT = "liquidity_drought"
    MACRO_UNCERTAINTY = "macro_uncertainty"


ALL_REGIME_LABELS: tuple[MarketRegimeLabel, ...] = tuple(MarketRegimeLabel)


class RegimeScopeType(str, Enum):
    INSTRUMENT = "instrument"
    SECTOR = "sector"
    GLOBAL = "global"


@dataclass(frozen=True, slots=True)
class RegimeFeatureVector:
    """Normalized observation vector fed into the Gaussian HMM."""

    trend_slope: float
    band_position: float
    vol_ratio: float
    vol_level: float
    volume_change: float
    spread_norm: float
    correlation_cluster: float

    def as_list(self) -> list[float]:
        return [
            self.trend_slope,
            self.band_position,
            self.vol_ratio,
            self.vol_level,
            self.volume_change,
            self.spread_norm,
            self.correlation_cluster,
        ]

    def as_dict(self) -> dict[str, float]:
        return {
            "trend_slope": self.trend_slope,
            "band_position": self.band_position,
            "vol_ratio": self.vol_ratio,
            "vol_level": self.vol_level,
            "volume_change": self.volume_change,
            "spread_norm": self.spread_norm,
            "correlation_cluster": self.correlation_cluster,
        }


@dataclass(frozen=True, slots=True)
class InstrumentSeries:
    """Price/volume/spread inputs for a single instrument."""

    prices: list[float]
    volumes: list[float] = field(default_factory=list)
    spread_bps: float | None = None


@dataclass(frozen=True, slots=True)
class RegimeClassificationResult:
    """Probabilistic regime output — distribution sums to 1.0."""

    distribution: dict[str, float]
    dominant_regime: str
    confidence: float
    feature_sequence: tuple[RegimeFeatureVector, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not self.distribution:
            raise ValueError("distribution must not be empty")
        total = sum(self.distribution.values())
        if not (0.999 <= total <= 1.001):
            raise ValueError(f"distribution must sum to 1.0, got {total}")
        if self.dominant_regime not in self.distribution:
            raise ValueError("dominant_regime must appear in distribution")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution": dict(self.distribution),
            "dominant_regime": self.dominant_regime,
            "confidence": self.confidence,
        }
