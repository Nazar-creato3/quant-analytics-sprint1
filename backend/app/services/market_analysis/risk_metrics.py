"""Core risk metrics from OHLCV (spec Section 3)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from app.services.quant_math import (
    VaRMethod,
    covariance,
    expected_shortfall,
    historical_volatility,
    log_return,
    value_at_risk,
)

_TRADING_DAYS_YEAR = 252
_DEFAULT_RF = 0.05


@dataclass(frozen=True, slots=True)
class InstrumentRiskMetrics:
    var_95: float | None
    cvar_95: float | None
    beta: float | None
    volatility: float | None
    sharpe: float | None
    max_drawdown: float | None
    tracking_error: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "var_95": self.var_95,
            "cvar_95": self.cvar_95,
            "beta": self.beta,
            "volatility": self.volatility,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "tracking_error": self.tracking_error,
        }


def returns_from_prices(prices: Sequence[float]) -> list[float]:
    if len(prices) < 2:
        return []
    returns: list[float] = []
    for index in range(1, len(prices)):
        prev, curr = prices[index - 1], prices[index]
        if prev <= 0 or curr <= 0:
            returns.append(0.0)
        else:
            returns.append(log_return(curr, prev))
    return returns


def compute_max_drawdown(prices: Sequence[float]) -> float | None:
    """Peak-to-trough drawdown as a positive fraction (0.25 = -25%)."""
    if len(prices) < 2:
        return None
    peak = prices[0]
    max_dd = 0.0
    for price in prices:
        if price > peak:
            peak = price
        if peak > 0:
            dd = (peak - price) / peak
            max_dd = max(max_dd, dd)
    return round(max_dd, 6)


def compute_beta(asset_returns: Sequence[float], market_returns: Sequence[float]) -> float | None:
    if len(asset_returns) < 2 or len(market_returns) < 2:
        return None
    length = min(len(asset_returns), len(market_returns))
    asset = list(asset_returns[-length:])
    market = list(market_returns[-length:])
    market_var = historical_volatility(market) ** 2
    if market_var <= 1e-16:
        return None
    return round(covariance(asset, market) / market_var, 4)


def compute_tracking_error(
    asset_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    *,
    annualize: bool = True,
) -> float | None:
    length = min(len(asset_returns), len(benchmark_returns))
    if length < 2:
        return None
    active = [
        asset_returns[i - length] - benchmark_returns[i - length]
        for i in range(length, 0, -1)
    ]
    te = historical_volatility(active)
    if annualize:
        te *= math.sqrt(_TRADING_DAYS_YEAR)
    return round(te, 6)


def compute_sharpe(
    returns: Sequence[float],
    *,
    risk_free_rate: float = _DEFAULT_RF,
) -> float | None:
    if len(returns) < 2:
        return None
    daily_rf = risk_free_rate / _TRADING_DAYS_YEAR
    excess = [value - daily_rf for value in returns]
    mean = sum(excess) / len(excess)
    vol = historical_volatility(excess)
    if vol <= 1e-12:
        return None
    return round(mean / vol * math.sqrt(_TRADING_DAYS_YEAR), 4)


def compute_risk_metrics_from_prices(
    prices: Sequence[float],
    *,
    benchmark_prices: Sequence[float] | None = None,
    risk_free_rate: float = _DEFAULT_RF,
) -> InstrumentRiskMetrics:
    """Historical VaR/CVaR, beta, vol, Sharpe, drawdown, tracking error."""
    returns = returns_from_prices(prices)
    if len(returns) < 5:
        return InstrumentRiskMetrics(
            var_95=None,
            cvar_95=None,
            beta=None,
            volatility=None,
            sharpe=None,
            max_drawdown=None,
            tracking_error=None,
        )

    var_95 = round(value_at_risk(returns, 0.95, method=VaRMethod.HISTORICAL), 6)
    cvar_95 = round(expected_shortfall(returns, 0.95, var_95), 6)
    daily_vol = historical_volatility(returns)
    annual_vol = round(daily_vol * math.sqrt(_TRADING_DAYS_YEAR), 6)

    benchmark_returns: list[float] = []
    if benchmark_prices:
        benchmark_returns = returns_from_prices(benchmark_prices)

    beta = compute_beta(returns, benchmark_returns) if benchmark_returns else None
    tracking = (
        compute_tracking_error(returns, benchmark_returns)
        if benchmark_returns
        else None
    )

    return InstrumentRiskMetrics(
        var_95=var_95,
        cvar_95=cvar_95,
        beta=beta,
        volatility=annual_vol,
        sharpe=compute_sharpe(returns, risk_free_rate=risk_free_rate),
        max_drawdown=compute_max_drawdown(prices),
        tracking_error=tracking,
    )
