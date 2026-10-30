"""Portfolio covariance and weight helpers for ScenarioEngine."""
from __future__ import annotations

import math
from typing import Mapping, Sequence

from app.services.quant_math import covariance, historical_volatility, portfolio_variance
from app.services.scenario.types import PortfolioPosition, PortfolioSnapshot


def weights_by_instrument(positions: Sequence[PortfolioPosition]) -> dict[int, float]:
    """Map instrument_id to portfolio weight."""
    weights: dict[int, float] = {}
    for position in positions:
        weights[position.instrument_id] = weights.get(position.instrument_id, 0.0) + position.weight
    return weights


def instrument_order(portfolio: PortfolioSnapshot) -> list[int]:
    """Stable instrument ordering for covariance matrices."""
    return sorted(weights_by_instrument(portfolio.positions).keys())


def weight_vector(portfolio: PortfolioSnapshot, order: Sequence[int]) -> list[float]:
    """Weight vector aligned to instrument order."""
    weights = weights_by_instrument(portfolio.positions)
    return [weights.get(instrument_id, 0.0) for instrument_id in order]


def build_covariance_matrix(
    returns_by_instrument: Mapping[int, Sequence[float]],
    order: Sequence[int],
) -> list[list[float]]:
    """Build sample covariance matrix aligned to instrument order."""
    size = len(order)
    matrix = [[0.0] * size for _ in range(size)]
    for row_index, left_id in enumerate(order):
        left_returns = list(returns_by_instrument.get(left_id, []))
        for col_index, right_id in enumerate(order):
            right_returns = list(returns_by_instrument.get(right_id, []))
            if row_index == col_index:
                if len(left_returns) >= 2:
                    vol = historical_volatility(left_returns)
                    matrix[row_index][col_index] = vol * vol
                continue
            length = min(len(left_returns), len(right_returns))
            if length < 2:
                matrix[row_index][col_index] = 0.0
            else:
                matrix[row_index][col_index] = covariance(
                    left_returns[-length:],
                    right_returns[-length:],
                )
    return matrix


def portfolio_variance_for(
    portfolio: PortfolioSnapshot,
    *,
    covariance_matrix: list[list[float]] | None = None,
) -> float:
    """Compute baseline portfolio variance w^T Sigma w."""
    order = instrument_order(portfolio)
    if not order:
        return 0.0
    weights = weight_vector(portfolio, order)
    sigma = covariance_matrix or build_covariance_matrix(portfolio.returns_by_instrument, order)
    return portfolio_variance(weights, sigma)


def stress_correlation_matrix(
    covariance_matrix: list[list[float]],
    shock_strength: float,
) -> list[list[float]]:
    """Increase pairwise correlations by shock_strength (fractional multiplier)."""
    size = len(covariance_matrix)
    if size == 0:
        return []

    volatilities = [
        math.sqrt(covariance_matrix[index][index]) if covariance_matrix[index][index] > 0.0 else 0.0
        for index in range(size)
    ]
    correlation = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for col in range(size):
            if row == col:
                correlation[row][col] = 1.0
                continue
            denom = volatilities[row] * volatilities[col]
            if denom <= 0.0:
                correlation[row][col] = 0.0
            else:
                correlation[row][col] = covariance_matrix[row][col] / denom

    blend = min(1.0, max(0.0, shock_strength))
    stressed_correlation = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for col in range(size):
            if row == col:
                stressed_correlation[row][col] = 1.0
            else:
                # Move pairwise correlation toward 1.0 (diversification breakdown).
                stressed_correlation[row][col] = min(
                    0.99,
                    correlation[row][col] + blend * (1.0 - correlation[row][col]),
                )

    stressed_covariance = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for col in range(size):
            stressed_covariance[row][col] = (
                stressed_correlation[row][col] * volatilities[row] * volatilities[col]
            )
    return stressed_covariance


def scale_diagonal_volatility(
    covariance_matrix: list[list[float]],
    vol_multipliers: Sequence[float],
) -> list[list[float]]:
    """Scale instrument volatilities while preserving correlation structure."""
    size = len(covariance_matrix)
    if size == 0:
        return []

    volatilities = [
        math.sqrt(covariance_matrix[index][index]) if covariance_matrix[index][index] > 0.0 else 0.0
        for index in range(size)
    ]
    correlation = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for col in range(size):
            if row == col:
                correlation[row][col] = 1.0
                continue
            denom = volatilities[row] * volatilities[col]
            if denom <= 0.0:
                correlation[row][col] = 0.0
            else:
                correlation[row][col] = covariance_matrix[row][col] / denom

    new_vols = [
        volatilities[index] * max(1.0, vol_multipliers[index])
        for index in range(size)
    ]
    scaled = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for col in range(size):
            scaled[row][col] = correlation[row][col] * new_vols[row] * new_vols[col]
    return scaled


def portfolio_return_series(
    returns_by_instrument: Mapping[int, Sequence[float]],
    weights_by_instrument: Mapping[int, float],
) -> list[float]:
    """Historical weighted portfolio return series."""
    active = {
        instrument_id: weight
        for instrument_id, weight in weights_by_instrument.items()
        if weight > 0.0
    }
    if not active:
        return []

    min_length = min(len(returns_by_instrument.get(instrument_id, [])) for instrument_id in active)
    if min_length < 1:
        return []

    series: list[float] = []
    for offset in range(min_length):
        total = 0.0
        index = -(min_length - offset)
        for instrument_id, weight in active.items():
            total += weight * returns_by_instrument[instrument_id][index]
        series.append(total)
    return series


def aggregate_sleeve_impacts(
    instrument_impacts: Sequence[tuple[str, float]],
) -> list[tuple[str, float, float]]:
    """Aggregate instrument P&L impacts by sleeve with contribution percentages."""
    sleeve_totals: dict[str, float] = {}
    for sleeve_id, impact in instrument_impacts:
        sleeve_totals[sleeve_id] = sleeve_totals.get(sleeve_id, 0.0) + impact

    total_abs = sum(abs(value) for value in sleeve_totals.values())
    ranked = sorted(sleeve_totals.items(), key=lambda item: item[1])
    result: list[tuple[str, float, float]] = []
    for sleeve_id, impact in ranked:
        contribution = (abs(impact) / total_abs * 100.0) if total_abs > 0.0 else 0.0
        result.append((sleeve_id, impact, contribution))
    return result
