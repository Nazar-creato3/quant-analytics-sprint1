"""Helpers for normalizing connector data into quant models."""
from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np

from app.services.terminal_platform.quant.models import (
    CovMatrix,
    ExpectedReturns,
    OHLCVBar,
    Portfolio,
    ReturnSeries,
)


def returns_from_ohlcv(
    bars: Sequence[OHLCVBar],
    *,
    symbol: str = "ASSET",
    periods_per_year: int = 252,
    method: str = "simple",
) -> ReturnSeries:
    """Convert OHLCV closes into a ReturnSeries."""
    if len(bars) < 2:
        raise ValueError("need at least 2 OHLCV bars to compute returns")
    closes = [float(bar.close) for bar in bars]
    values: list[float] = []
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev <= 0.0 or cur <= 0.0:
            raise ValueError("OHLCV closes must be strictly positive")
        if method == "log":
            values.append(math.log(cur / prev))
        else:
            values.append(cur / prev - 1.0)
    return ReturnSeries(symbol=symbol, values=values, periods_per_year=periods_per_year)


def returns_from_prices(
    prices: Sequence[float],
    *,
    symbol: str = "ASSET",
    periods_per_year: int = 252,
    method: str = "simple",
) -> ReturnSeries:
    """Convert price levels into returns."""
    if len(prices) < 2:
        raise ValueError("need at least 2 prices")
    values: list[float] = []
    for i in range(1, len(prices)):
        prev, cur = float(prices[i - 1]), float(prices[i])
        if prev <= 0.0 or cur <= 0.0:
            raise ValueError("prices must be strictly positive")
        if method == "log":
            values.append(math.log(cur / prev))
        else:
            values.append(cur / prev - 1.0)
    return ReturnSeries(symbol=symbol, values=values, periods_per_year=periods_per_year)


def build_cov_matrix(
    returns_by_asset: Mapping[str, Sequence[float]],
) -> CovMatrix:
    """Sample covariance matrix from aligned return series."""
    symbols = list(returns_by_asset.keys())
    if not symbols:
        raise ValueError("returns_by_asset must not be empty")
    lengths = {len(returns_by_asset[s]) for s in symbols}
    if len(lengths) != 1:
        raise ValueError("all asset return series must have equal length")
    matrix = np.array([list(returns_by_asset[s]) for s in symbols], dtype=float)
    if matrix.shape[1] < 2:
        raise ValueError("need at least 2 observations for covariance")
    cov = np.cov(matrix, ddof=1)
    if cov.ndim == 0:
        cov = np.array([[float(cov)]])
    return CovMatrix(symbols=symbols, matrix=cov.tolist())


def build_expected_returns(
    returns_by_asset: Mapping[str, Sequence[float]],
    *,
    annualize: bool = False,
    periods_per_year: int = 252,
) -> ExpectedReturns:
    """Mean returns (optionally annualized) per asset."""
    symbols = list(returns_by_asset.keys())
    values: list[float] = []
    for symbol in symbols:
        series = list(returns_by_asset[symbol])
        if not series:
            raise ValueError(f"empty returns for {symbol}")
        mean = float(np.mean(series))
        if annualize:
            mean *= periods_per_year
        values.append(mean)
    return ExpectedReturns(symbols=symbols, values=values)


def portfolio_return_series(
    portfolio: Portfolio,
    returns_by_asset: Mapping[str, Sequence[float]],
) -> ReturnSeries:
    """Weighted portfolio return path from component returns."""
    symbols = [p.symbol for p in portfolio.positions]
    weights = np.array([p.weight for p in portfolio.positions], dtype=float)
    weight_sum = float(np.sum(weights))
    if abs(weight_sum) < 1e-12:
        raise ValueError("portfolio weights sum to zero")
    weights = weights / weight_sum

    series_list = []
    for symbol in symbols:
        if symbol not in returns_by_asset:
            raise ValueError(f"missing returns for {symbol}")
        series_list.append(list(returns_by_asset[symbol]))
    lengths = {len(s) for s in series_list}
    if len(lengths) != 1:
        raise ValueError("component return lengths must match")
    mat = np.array(series_list, dtype=float)
    port = weights @ mat
    return ReturnSeries(symbol=portfolio.name, values=port.tolist())


def annualize_volatility(period_vol: float, periods_per_year: int = 252) -> float:
    return float(period_vol * math.sqrt(periods_per_year))


def annualize_return(period_mean: float, periods_per_year: int = 252) -> float:
    return float(period_mean * periods_per_year)
