"""Conformal prediction intervals — MAPIE when available, split-conformal fallback."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from app.core.logging import get_logger

logger = get_logger(__name__)

HORIZON_DAYS = 30


@dataclass(frozen=True, slots=True)
class ConformalInterval:
    horizon_days: int
    median_return: float
    lower_70: float
    upper_70: float
    lower_90: float
    upper_90: float
    method: str
    sufficient_data: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "horizon_days": self.horizon_days,
            "median_return": self.median_return,
            "lower_70": self.lower_70,
            "upper_70": self.upper_70,
            "lower_90": self.lower_90,
            "upper_90": self.upper_90,
            "method": self.method,
            "sufficient_data": self.sufficient_data,
        }


def _split_conformal_intervals(
    returns: np.ndarray,
    point_forecast: float,
    *,
    horizon_days: int,
) -> ConformalInterval:
    """Split-conformal: calibration residuals on hold-out tail."""
    if len(returns) < 30:
        vol = float(np.std(returns)) if len(returns) > 1 else 0.02
        scale = vol * np.sqrt(min(horizon_days, 10))
        return ConformalInterval(
            horizon_days=horizon_days,
            median_return=point_forecast,
            lower_70=point_forecast - 1.04 * scale,
            upper_70=point_forecast + 1.04 * scale,
            lower_90=point_forecast - 1.645 * scale,
            upper_90=point_forecast + 1.645 * scale,
            method="vol_scaled_fallback",
            sufficient_data=False,
        )

    split = int(len(returns) * 0.7)
    train, cal = returns[:split], returns[split:]
    if len(cal) < 5:
        cal = returns[-20:]
        train = returns[:-20]

    naive_pred = np.mean(train[-5:]) if len(train) >= 5 else np.mean(train)
    residuals = np.abs(cal - naive_pred)
    q70 = float(np.quantile(residuals, 0.70))
    q90 = float(np.quantile(residuals, 0.90))
    scale = np.sqrt(min(horizon_days, 10))

    return ConformalInterval(
        horizon_days=horizon_days,
        median_return=point_forecast,
        lower_70=point_forecast - q70 * scale,
        upper_70=point_forecast + q70 * scale,
        lower_90=point_forecast - q90 * scale,
        upper_90=point_forecast + q90 * scale,
        method="split_conformal",
        sufficient_data=True,
    )


def _mapie_intervals(
    prices: Sequence[float],
    point_forecast: float,
    *,
    horizon_days: int,
) -> ConformalInterval | None:
    try:
        from mapie.regression import MapieRegressor  # type: ignore[import-untyped]
        from sklearn.linear_model import Ridge

        returns = np.diff(np.log(np.maximum(prices, 1e-9)))
        if len(returns) < 40:
            return None
        X = np.arange(len(returns)).reshape(-1, 1)
        y = returns
        estimator = Ridge(alpha=1.0)
        mapie = MapieRegressor(estimator, method="plus", cv=5)
        mapie.fit(X, y)
        x_pred = np.array([[len(returns) + horizon_days // 2]])
        _, intervals = mapie.predict(x_pred, alpha=[0.30, 0.10])
        lower_70 = float(point_forecast + intervals[0, 0, 0] * horizon_days)
        upper_70 = float(point_forecast + intervals[0, 0, 1] * horizon_days)
        lower_90 = float(point_forecast + intervals[1, 0, 0] * horizon_days)
        upper_90 = float(point_forecast + intervals[1, 0, 1] * horizon_days)
        return ConformalInterval(
            horizon_days=horizon_days,
            median_return=point_forecast,
            lower_70=lower_70,
            upper_70=upper_70,
            lower_90=lower_90,
            upper_90=upper_90,
            method="mapie_plus",
            sufficient_data=True,
        )
    except ImportError:
        return None
    except Exception as exc:
        logger.debug("MAPIE interval failed", error=str(exc))
        return None


def cheap_return_interval(
    prices: Sequence[float],
    point_forecast: float,
    *,
    horizon_days: int = HORIZON_DAYS,
) -> ConformalInterval:
    """Split-conformal only — safe on the maneuver hot path (no MAPIE)."""
    returns = np.diff(np.log(np.maximum(np.asarray(prices, dtype=float), 1e-9)))
    return _split_conformal_intervals(returns, point_forecast, horizon_days=horizon_days)


def compute_conformal_intervals(
    prices: Sequence[float],
    point_forecast: float,
    *,
    horizon_days: int = HORIZON_DAYS,
) -> ConformalInterval:
    """Produce calibrated 70% and 90% prediction intervals."""
    returns = np.diff(np.log(np.maximum(prices, 1e-9)))
    mapie_result = _mapie_intervals(prices, point_forecast, horizon_days=horizon_days)
    if mapie_result is not None:
        return mapie_result
    return _split_conformal_intervals(returns, point_forecast, horizon_days=horizon_days)
