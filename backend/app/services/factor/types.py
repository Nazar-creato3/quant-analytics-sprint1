"""Factor decomposition types for Prompt 19 Factor Engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FactorName(StrEnum):
    """Supported risk factors in the multi-factor model."""

    MARKET_BETA = "market_beta"
    SECTOR_FACTOR = "sector_factor"
    MOMENTUM = "momentum"
    VALUE = "value"
    GROWTH = "growth"
    VOLATILITY_FACTOR = "volatility_factor"
    RATES_SENSITIVITY = "rates_sensitivity"
    FX_SENSITIVITY = "fx_sensitivity"
    COMMODITY_SENSITIVITY = "commodity_sensitivity"
    MACRO_SHOCK_SENSITIVITY = "macro_shock_sensitivity"


ALL_FACTORS: tuple[FactorName, ...] = tuple(FactorName)


@dataclass(frozen=True, slots=True)
class FactorExposureRow:
    """Single factor beta estimate at a point in time."""

    instrument_id: int
    time: datetime
    factor_name: FactorName
    beta: float
    r_squared_of_model: float


@dataclass(frozen=True, slots=True)
class RollingFactorModelResult:
    """Output of one rolling-window multi-factor regression."""

    time_index: int
    betas: dict[FactorName, float]
    r_squared: float
