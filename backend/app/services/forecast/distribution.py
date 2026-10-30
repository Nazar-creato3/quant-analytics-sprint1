"""Unified forecast distribution — point, signal, and quantiles from one model."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.forecast.types import ForecastDirection
from app.services.quant_math import historical_volatility
from app.services.regime.features import prices_to_returns

from app.services.forecast.forecast_defaults import DEFAULT_INTERVAL_HORIZON_DAYS

INTERVAL_HORIZON_DAYS = DEFAULT_INTERVAL_HORIZON_DAYS
INTERVAL_CONFIDENCE_MULTIPLIER = 1.645
WEAK_SIGNAL_THRESHOLD = 0.30
DIRECTIONAL_SIGNAL_THRESHOLD = 0.35
# Single-name short-horizon direction lacks sustained edge — always flag unless strong signal.
SINGLE_NAME_DIRECTION_LOW_CONFIDENCE = True


@dataclass(frozen=True, slots=True)
class ForecastDistribution:
    """Single-source forecast output for tools, API, and validation."""

    point_direction: str
    signal_strength: float
    momentum_score: float
    p10: float
    p50: float
    p90: float
    horizon_days: int
    low_confidence: bool
    insufficient_data: bool
    symmetric_interval: bool
    data_quality: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "point_direction": self.point_direction,
            "signal_strength": round(self.signal_strength, 4),
            "momentum_score": round(self.momentum_score, 4),
            "p10": round(self.p10, 6),
            "p50": round(self.p50, 6),
            "p90": round(self.p90, 6),
            "horizon_days": self.horizon_days,
            "low_confidence": self.low_confidence,
            "insufficient_data": self.insufficient_data,
            "symmetric_interval": self.symmetric_interval,
            "data_quality": dict(self.data_quality),
        }


def _direction_label(direction: ForecastDirection) -> str:
    if direction == ForecastDirection.BULLISH:
        return "increase"
    if direction == ForecastDirection.BEARISH:
        return "decrease"
    return "neutral"


def build_forecast_distribution(
    *,
    prices: Sequence[float],
    momentum_score: float,
    direction: ForecastDirection,
    horizon_days: int = INTERVAL_HORIZON_DAYS,
) -> ForecastDistribution:
    """Derive point direction, signal strength, and quantile band from aligned inputs."""
    returns = prices_to_returns(list(prices))
    data_quality: dict[str, str] = {}

    if len(returns) < 5:
        data_quality["returns"] = "insufficient_data"
        return ForecastDistribution(
            point_direction="neutral",
            signal_strength=0.0,
            momentum_score=momentum_score,
            p10=0.0,
            p50=0.0,
            p90=0.0,
            horizon_days=horizon_days,
            low_confidence=True,
            insufficient_data=True,
            symmetric_interval=True,
            data_quality=data_quality,
        )

    vol = historical_volatility(returns)
    if vol <= 1e-9:
        data_quality["volatility"] = "insufficient_data"
        vol = 0.02

    half_width = vol * INTERVAL_CONFIDENCE_MULTIPLIER
    drift = (momentum_score - 0.5) * half_width * 2.0
    sign = 0
    if direction == ForecastDirection.BULLISH:
        sign = 1
    elif direction == ForecastDirection.BEARISH:
        sign = -1

    if sign != 0 and momentum_score >= DIRECTIONAL_SIGNAL_THRESHOLD:
        p10 = drift - half_width * (1.0 - sign * 0.35)
        p90 = drift + half_width * (1.0 + sign * 0.35)
    else:
        p10 = -half_width
        p90 = half_width

    p50 = drift
    symmetric = abs(p10 + p90) < 1e-6 or (abs(p10) == abs(p90) and abs(drift) < half_width * 0.15)
    low_conf = (
        momentum_score < WEAK_SIGNAL_THRESHOLD
        or symmetric
        or SINGLE_NAME_DIRECTION_LOW_CONFIDENCE
    )

    return ForecastDistribution(
        point_direction=_direction_label(direction),
        signal_strength=momentum_score,
        momentum_score=momentum_score,
        p10=p10,
        p50=p50,
        p90=p90,
        horizon_days=horizon_days,
        low_confidence=low_conf,
        insufficient_data=False,
        symmetric_interval=symmetric,
        data_quality=data_quality,
    )
