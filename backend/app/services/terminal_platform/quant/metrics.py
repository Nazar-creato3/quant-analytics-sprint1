"""Core portfolio / return metrics (Sharpe, Sortino, CAGR, vol, DD, beta, corr)."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from app.services.quant_math import correlation as qm_correlation
from app.services.quant_math import covariance as qm_covariance
from app.services.quant_math import historical_volatility
from app.services.terminal_platform.quant.models import (
    PriceSeries,
    ReturnSeries,
    RiskMetrics,
)


def sharpe_ratio(
    returns: ReturnSeries | Sequence[float],
    risk_free_rate: float | None = None,
    *,
    periods_per_year: int | None = None,
) -> float:
    """Annualized Sharpe = sqrt(N) * mean(excess) / std(excess)."""
    values, ppy, rf = _unpack_returns(returns, risk_free_rate, periods_per_year)
    if len(values) < 2:
        return 0.0
    excess = values - (rf / ppy)
    std = float(np.std(excess, ddof=1))
    if std <= 1e-15:
        return 0.0
    return float(np.mean(excess) / std * math.sqrt(ppy))


def sortino_ratio(
    returns: ReturnSeries | Sequence[float],
    risk_free_rate: float | None = None,
    *,
    periods_per_year: int | None = None,
) -> float:
    """Annualized Sortino using downside deviation vs period risk-free."""
    values, ppy, rf = _unpack_returns(returns, risk_free_rate, periods_per_year)
    if len(values) < 2:
        return 0.0
    period_rf = rf / ppy
    excess = values - period_rf
    downside = np.minimum(excess, 0.0)
    downside_var = float(np.mean(downside**2))
    downside_std = math.sqrt(downside_var)
    if downside_std <= 1e-15:
        return 0.0
    return float(np.mean(excess) / downside_std * math.sqrt(ppy))


def cagr(prices: PriceSeries | Sequence[float], *, periods_per_year: int | None = None) -> float:
    """Compound annual growth rate from a price path."""
    if isinstance(prices, PriceSeries):
        values = np.asarray(prices.values, dtype=float)
        ppy = periods_per_year or prices.periods_per_year
    else:
        values = np.asarray(list(prices), dtype=float)
        ppy = periods_per_year or 252
    if len(values) < 2:
        return 0.0
    start, end = float(values[0]), float(values[-1])
    if start <= 0.0 or end <= 0.0:
        raise ValueError("prices must be strictly positive for CAGR")
    n_periods = len(values) - 1
    years = n_periods / float(ppy)
    if years <= 0.0:
        return 0.0
    return float((end / start) ** (1.0 / years) - 1.0)


def volatility(
    returns: ReturnSeries | Sequence[float],
    *,
    annualize: bool = False,
    periods_per_year: int | None = None,
) -> float:
    """Sample volatility; optionally annualize with √N."""
    values, ppy, _ = _unpack_returns(returns, None, periods_per_year)
    vol = float(historical_volatility(values.tolist()))
    if annualize:
        return vol * math.sqrt(ppy)
    return vol


def max_drawdown(prices: PriceSeries | Sequence[float]) -> float:
    """Maximum peak-to-trough drawdown as a positive fraction."""
    if isinstance(prices, PriceSeries):
        values = np.asarray(prices.values, dtype=float)
    else:
        values = np.asarray(list(prices), dtype=float)
    if len(values) < 2:
        return 0.0
    peak = values[0]
    worst = 0.0
    for price in values:
        if price > peak:
            peak = price
        if peak <= 0.0:
            continue
        dd = (peak - price) / peak
        if dd > worst:
            worst = dd
    return float(worst)


def beta(
    returns: ReturnSeries | Sequence[float],
    benchmark_returns: ReturnSeries | Sequence[float],
) -> float:
    """CAPM beta = Cov(r, m) / Var(m)."""
    r = _as_array(returns)
    b = _as_array(benchmark_returns)
    if len(r) != len(b):
        raise ValueError("returns and benchmark must have equal length")
    if len(r) < 2:
        return 0.0
    var_b = float(np.var(b, ddof=1))
    if var_b <= 1e-15:
        return 0.0
    return float(qm_covariance(r.tolist(), b.tolist()) / var_b)


def correlation_pair(
    returns_a: ReturnSeries | Sequence[float],
    returns_b: ReturnSeries | Sequence[float],
) -> float:
    """Pearson correlation between two return series."""
    a = _as_array(returns_a)
    b = _as_array(returns_b)
    if len(a) != len(b):
        raise ValueError("series must have equal length")
    return float(qm_correlation(a.tolist(), b.tolist()))


def compute_risk_metrics(
    returns: ReturnSeries,
    *,
    prices: PriceSeries | None = None,
    benchmark_returns: ReturnSeries | None = None,
) -> RiskMetrics:
    """Compute the full Terminal RiskMetrics bundle."""
    vol = volatility(returns, annualize=False)
    vol_ann = volatility(returns, annualize=True)
    dd = 0.0
    cagr_value: float | None = None
    if prices is not None:
        dd = max_drawdown(prices)
        cagr_value = cagr(prices)
    else:
        # Reconstruct a unit equity path from returns for drawdown.
        equity = np.cumprod(1.0 + np.asarray(returns.values, dtype=float))
        equity = np.insert(equity, 0, 1.0)
        dd = max_drawdown(equity.tolist())

    beta_value: float | None = None
    corr_value: float | None = None
    if benchmark_returns is not None:
        # Align lengths if needed (truncate to min).
        n = min(len(returns.values), len(benchmark_returns.values))
        r = ReturnSeries(
            symbol=returns.symbol,
            values=returns.values[-n:],
            periods_per_year=returns.periods_per_year,
            risk_free_rate=returns.risk_free_rate,
        )
        b = ReturnSeries(
            symbol=benchmark_returns.symbol,
            values=benchmark_returns.values[-n:],
            periods_per_year=benchmark_returns.periods_per_year,
        )
        beta_value = beta(r, b)
        corr_value = correlation_pair(r, b)

    return RiskMetrics(
        sharpe=sharpe_ratio(returns),
        sortino=sortino_ratio(returns),
        cagr=cagr_value,
        volatility=vol,
        volatility_annual=vol_ann,
        max_drawdown=dd,
        beta=beta_value,
        correlation=corr_value,
        periods_per_year=returns.periods_per_year,
        n_observations=len(returns.values),
    )


def _unpack_returns(
    returns: ReturnSeries | Sequence[float],
    risk_free_rate: float | None,
    periods_per_year: int | None,
) -> tuple[np.ndarray, int, float]:
    if isinstance(returns, ReturnSeries):
        values = np.asarray(returns.values, dtype=float)
        ppy = periods_per_year or returns.periods_per_year
        rf = returns.risk_free_rate if risk_free_rate is None else risk_free_rate
    else:
        values = np.asarray(list(returns), dtype=float)
        ppy = periods_per_year or 252
        rf = 0.0 if risk_free_rate is None else risk_free_rate
    return values, ppy, rf


def _as_array(returns: ReturnSeries | Sequence[float]) -> np.ndarray:
    if isinstance(returns, ReturnSeries):
        return np.asarray(returns.values, dtype=float)
    return np.asarray(list(returns), dtype=float)
