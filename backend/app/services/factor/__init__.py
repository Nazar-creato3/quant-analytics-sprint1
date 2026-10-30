"""Factor decomposition engine (Prompt 19)."""
from __future__ import annotations

from app.services.factor.engine import FactorEngine, FactorEngineConfig
from app.services.factor.regression import ols_multivariate, rolling_factor_regression
from app.services.factor.types import ALL_FACTORS, FactorExposureRow, FactorName

__all__ = [
    "ALL_FACTORS",
    "FactorEngine",
    "FactorEngineConfig",
    "FactorExposureRow",
    "FactorName",
    "ols_multivariate",
    "rolling_factor_regression",
]
