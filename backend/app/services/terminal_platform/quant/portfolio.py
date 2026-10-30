"""Mean-variance portfolio analytics: Efficient Frontier, max Sharpe, min variance."""
from __future__ import annotations

import math

import numpy as np

from app.services.quant_math import portfolio_variance
from app.services.terminal_platform.quant.models import (
    CovMatrix,
    EfficientFrontierResult,
    ExpectedReturns,
    FrontierPoint,
    OptimizedPortfolio,
)


def optimize_min_variance(
    expected_returns: ExpectedReturns,
    cov_matrix: CovMatrix,
    *,
    long_only: bool = True,
    risk_free_rate: float = 0.0,
) -> OptimizedPortfolio:
    """Global minimum-variance portfolio (weights sum to 1)."""
    _align(expected_returns, cov_matrix)
    cov = np.asarray(cov_matrix.matrix, dtype=float)
    weights = _min_variance_weights(cov, long_only=long_only)
    return _pack(
        symbols=cov_matrix.symbols,
        weights=weights,
        mu=np.asarray(expected_returns.values, dtype=float),
        cov=cov,
        risk_free_rate=risk_free_rate,
        objective="min_variance",
    )


def optimize_sharpe(
    expected_returns: ExpectedReturns,
    cov_matrix: CovMatrix,
    *,
    risk_free_rate: float = 0.0,
    long_only: bool = True,
) -> OptimizedPortfolio:
    """Maximum Sharpe portfolio (tangency / excess-return solution)."""
    _align(expected_returns, cov_matrix)
    mu = np.asarray(expected_returns.values, dtype=float)
    cov = np.asarray(cov_matrix.matrix, dtype=float)
    excess = mu - risk_free_rate
    inv = np.linalg.pinv(cov)
    raw = inv @ excess
    if float(np.sum(np.abs(raw))) < 1e-15:
        weights = np.ones(len(mu)) / len(mu)
    else:
        weights = raw / float(np.sum(raw))
    if long_only:
        weights = _project_long_only(weights)
    return _pack(
        symbols=cov_matrix.symbols,
        weights=weights,
        mu=mu,
        cov=cov,
        risk_free_rate=risk_free_rate,
        objective="max_sharpe",
    )


def efficient_frontier(
    expected_returns: ExpectedReturns,
    cov_matrix: CovMatrix,
    *,
    n_points: int = 25,
    risk_free_rate: float = 0.0,
    long_only: bool = True,
) -> EfficientFrontierResult:
    """Trace mean-variance frontier between min and max asset expected returns."""
    _align(expected_returns, cov_matrix)
    if n_points < 3:
        raise ValueError("n_points must be >= 3")

    mu = np.asarray(expected_returns.values, dtype=float)
    cov = np.asarray(cov_matrix.matrix, dtype=float)
    min_var = optimize_min_variance(
        expected_returns, cov_matrix, long_only=long_only, risk_free_rate=risk_free_rate
    )
    max_sharpe = optimize_sharpe(
        expected_returns, cov_matrix, long_only=long_only, risk_free_rate=risk_free_rate
    )

    target_min = float(np.min(mu))
    target_max = float(np.max(mu))
    if abs(target_max - target_min) < 1e-15:
        target_max = target_min + 1e-6

    targets = np.linspace(target_min, target_max, n_points)
    points: list[FrontierPoint] = []
    for target in targets:
        weights = _target_return_weights(mu, cov, float(target), long_only=long_only)
        vol = math.sqrt(max(0.0, float(portfolio_variance(weights.tolist(), cov.tolist()))))
        ret = float(weights @ mu)
        sharpe = (ret - risk_free_rate) / vol if vol > 1e-15 else 0.0
        points.append(
            FrontierPoint(
                target_return=ret,
                volatility=vol,
                sharpe=float(sharpe),
                weights=weights.tolist(),
            )
        )

    return EfficientFrontierResult(
        symbols=list(cov_matrix.symbols),
        points=points,
        max_sharpe=max_sharpe,
        min_variance=min_var,
    )


def _min_variance_weights(cov: np.ndarray, *, long_only: bool) -> np.ndarray:
    n = cov.shape[0]
    ones = np.ones(n)
    inv = np.linalg.pinv(cov)
    raw = inv @ ones
    denom = float(ones @ raw)
    if abs(denom) < 1e-15:
        weights = ones / n
    else:
        weights = raw / denom
    if long_only:
        weights = _project_long_only(weights)
    return weights


def _target_return_weights(
    mu: np.ndarray,
    cov: np.ndarray,
    target: float,
    *,
    long_only: bool,
) -> np.ndarray:
    """Analytical two-constraint Markowitz solution, then optional long-only projection."""
    n = len(mu)
    ones = np.ones(n)
    inv = np.linalg.pinv(cov)
    a = float(ones @ inv @ ones)
    b = float(ones @ inv @ mu)
    c = float(mu @ inv @ mu)
    det = a * c - b * b
    if abs(det) < 1e-18:
        weights = _min_variance_weights(cov, long_only=long_only)
        return weights
    lambda_ = (c - b * target) / det
    gamma = (a * target - b) / det
    weights = inv @ (lambda_ * ones + gamma * mu)
    if long_only:
        weights = _project_long_only(weights)
        # Soft re-target: blend toward equal weight of assets nearest the target.
        # Keep fully invested long-only even if exact target is infeasible.
    return weights


def _project_long_only(weights: np.ndarray) -> np.ndarray:
    clipped = np.maximum(weights, 0.0)
    total = float(np.sum(clipped))
    if total <= 1e-15:
        return np.ones(len(weights)) / len(weights)
    return clipped / total


def _pack(
    *,
    symbols: list[str],
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    risk_free_rate: float,
    objective: str,
) -> OptimizedPortfolio:
    ret = float(weights @ mu)
    var = float(portfolio_variance(weights.tolist(), cov.tolist()))
    vol = math.sqrt(max(0.0, var))
    sharpe = (ret - risk_free_rate) / vol if vol > 1e-15 else 0.0
    return OptimizedPortfolio(
        symbols=list(symbols),
        weights=weights.tolist(),
        expected_return=ret,
        volatility=vol,
        sharpe=float(sharpe),
        objective=objective,
        metadata={"weight_sum": float(np.sum(weights))},
    )


def _align(expected_returns: ExpectedReturns, cov_matrix: CovMatrix) -> None:
    if expected_returns.symbols != cov_matrix.symbols:
        raise ValueError("expected_returns.symbols must match cov_matrix.symbols")
