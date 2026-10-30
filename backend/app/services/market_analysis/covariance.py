"""Factor-implied covariance Σ = B F B' + D (spec Section 2.2)."""
from __future__ import annotations

import math
from typing import Mapping, Sequence

STYLE_FACTORS: tuple[str, ...] = (
    "value",
    "momentum",
    "size",
    "quality",
    "low_vol",
    "growth",
    "liquidity",
)


def _outer_product(vec: Sequence[float]) -> list[list[float]]:
    return [[vec[i] * vec[j] for j in range(len(vec))] for i in range(len(vec))]


def factor_covariance_from_returns(
    factor_return_series: Mapping[str, Sequence[float]],
    *,
    factor_order: Sequence[str] | None = None,
) -> tuple[list[list[float]], list[str]]:
    """Sample covariance matrix F from aligned factor return series."""
    order = list(factor_order or STYLE_FACTORS)
    present = [name for name in order if name in factor_return_series and len(factor_return_series[name]) >= 2]
    if len(present) < 1:
        return [[0.0]], []

    length = min(len(factor_return_series[name]) for name in present)
    matrix_size = len(present)
    cov = [[0.0] * matrix_size for _ in range(matrix_size)]

    for i, fi in enumerate(present):
        series_i = list(factor_return_series[fi][-length:])
        mean_i = sum(series_i) / len(series_i)
        for j, fj in enumerate(present):
            series_j = list(factor_return_series[fj][-length:])
            mean_j = sum(series_j) / len(series_j)
            if length < 2:
                cov[i][j] = 0.0
            else:
                cov[i][j] = sum(
                    (series_i[t] - mean_i) * (series_j[t] - mean_j) for t in range(length)
                ) / (length - 1)
    return cov, present


def factor_implied_variance(
    exposures: Mapping[str, float | None],
    factor_covariance: Sequence[Sequence[float]],
    *,
    factor_order: Sequence[str],
    idiosyncratic_variance: float,
) -> dict[str, float | list[list[float]] | list[str]]:
    """
    Single-asset variance: σ² = β' F β + ε².
    Returns implied variance/volatility and the exposure vector used.
    """
    beta = [float(exposures.get(name) or 0.0) for name in factor_order]
    system = 0.0
    size = len(factor_order)
    for i in range(size):
        for j in range(size):
            system += beta[i] * factor_covariance[i][j] * beta[j]
    total = max(0.0, system + max(0.0, idiosyncratic_variance))
    implied_vol = math.sqrt(total) if total > 0 else 0.0
    return {
        "factor_order": list(factor_order),
        "exposure_vector": [round(value, 4) for value in beta],
        "factor_covariance": [[round(factor_covariance[i][j], 8) for j in range(size)] for i in range(size)],
        "systematic_variance": round(system, 8),
        "idiosyncratic_variance": round(max(0.0, idiosyncratic_variance), 8),
        "implied_variance": round(total, 8),
        "implied_volatility": round(implied_vol * math.sqrt(252), 6),
    }


def estimate_idiosyncratic_variance(
    asset_returns: Sequence[float],
    factor_returns: Mapping[str, Sequence[float]],
    exposures: Mapping[str, float | None],
    *,
    factor_order: Sequence[str] | None = None,
) -> float:
    """Residual variance after factor projection (diagonal D entry)."""
    order = list(factor_order or STYLE_FACTORS)
    length = min(len(asset_returns), *(len(factor_returns[f]) for f in order if f in factor_returns))
    if length < 3:
        if len(asset_returns) >= 2:
            vol = sum(asset_returns) / len(asset_returns)
            var = sum((r - vol) ** 2 for r in asset_returns) / (len(asset_returns) - 1)
            return max(0.0, var)
        return 0.0

    residuals: list[float] = []
    for t in range(length):
        explained = 0.0
        for name in order:
            beta = float(exposures.get(name) or 0.0)
            explained += beta * float(factor_returns[name][t])
        residuals.append(asset_returns[t] - explained)

    mean = sum(residuals) / len(residuals)
    return max(
        0.0,
        sum((value - mean) ** 2 for value in residuals) / (len(residuals) - 1),
    )
