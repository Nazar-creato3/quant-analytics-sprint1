"""Pure quantitative math functions for risk analytics."""
from __future__ import annotations

import math
from enum import Enum
from typing import Sequence


class VaRMethod(str, Enum):
    """Supported value-at-risk estimation methods."""

    HISTORICAL = "historical"
    PARAMETRIC = "parametric"


def log_return(p_t: float, p_t_minus_1: float) -> float:
    """Compute log return.

    Formula: r_t = ln(P_t / P_t_minus_1)
    """
    _validate_finite(p_t, p_t_minus_1)
    if p_t <= 0.0 or p_t_minus_1 <= 0.0:
        raise ValueError("Prices must be strictly positive for log returns.")
    return math.log(p_t / p_t_minus_1)


def historical_volatility(returns: Sequence[float]) -> float:
    """Compute sample historical volatility (standard deviation).

    Formula: sqrt(1/(n-1) * sum((r_t - mean_r)^2))
    """
    values = _validate_returns(returns)
    n = len(values)
    if n < 2:
        return 0.0

    mean_r = sum(values) / n
    variance = sum((value - mean_r) ** 2 for value in values) / (n - 1)
    return math.sqrt(variance)


def rolling_volatility(returns: Sequence[float], window: int) -> list[float]:
    """Compute rolling sample standard deviation over a fixed window.

    Formula per window: sqrt(1/(window-1) * sum((r_t - mean_r)^2))
    Positions with fewer than ``window`` observations are ``nan``.
    """
    if window < 1:
        raise ValueError("window must be >= 1.")
    if not isinstance(window, int):
        raise TypeError("window must be an integer.")

    values = _validate_returns(returns)
    n = len(values)
    result = [math.nan] * n
    if n < window:
        return result

    # Values are validated once above; same formula as historical_volatility per window,
    # without re-validating every slice (that check was most of the cost).
    for index in range(window - 1, n):
        window_slice = values[index - window + 1 : index + 1]
        if window < 2:
            result[index] = 0.0
            continue
        mean_r = sum(window_slice) / window
        variance = sum((value - mean_r) ** 2 for value in window_slice) / (window - 1)
        result[index] = math.sqrt(variance)
    return result


def covariance(x: Sequence[float], y: Sequence[float]) -> float:
    """Compute sample covariance between two series.

    Formula: 1/(n-1) * sum((x_t - mean_x) * (y_t - mean_y))
    """
    x_values = _validate_returns(x, name="x")
    y_values = _validate_returns(y, name="y")
    if len(x_values) != len(y_values):
        raise ValueError("x and y must have the same length.")

    n = len(x_values)
    if n < 2:
        return 0.0

    mean_x = sum(x_values) / n
    mean_y = sum(y_values) / n
    return sum(
        (x_values[index] - mean_x) * (y_values[index] - mean_y)
        for index in range(n)
    ) / (n - 1)


def correlation(x: Sequence[float], y: Sequence[float]) -> float:
    """Compute Pearson correlation coefficient.

    Formula: covariance(x, y) / (std(x) * std(y))
    """
    std_x = historical_volatility(x)
    std_y = historical_volatility(y)
    if std_x == 0.0 or std_y == 0.0:
        return 0.0
    return covariance(x, y) / (std_x * std_y)


def portfolio_variance(
    weights: Sequence[float],
    covariance_matrix: Sequence[Sequence[float]],
) -> float:
    """Compute portfolio variance.

    Formula: w^T * Sigma * w
    """
    w = _validate_weights(weights)
    sigma = _validate_covariance_matrix(covariance_matrix, size=len(w))

    total = 0.0
    for i, weight_i in enumerate(w):
        row = sigma[i]
        for j, weight_j in enumerate(w):
            total += weight_i * row[j] * weight_j
    return total


def value_at_risk(
    returns: Sequence[float],
    alpha: float,
    *,
    method: VaRMethod = VaRMethod.HISTORICAL,
) -> float:
    """Estimate value-at-risk as a positive loss magnitude.

    Historical method: alpha-quantile of the loss distribution (-returns).
    Parametric method: -(mean + z_{1-alpha} * std) under a normal return model.
    """
    values = _validate_returns(returns)
    _validate_alpha(alpha)

    if method == VaRMethod.HISTORICAL:
        return _historical_var(values, alpha)
    if method == VaRMethod.PARAMETRIC:
        return _parametric_var(values, alpha)
    raise ValueError(f"Unsupported VaR method: {method!r}.")


def expected_shortfall(
    returns: Sequence[float],
    alpha: float,
    var_value: float,
) -> float:
    """Compute expected shortfall (conditional tail loss beyond VaR).

    Formula: mean(-r_t | -r_t >= VaR_alpha), reported as a positive loss magnitude.
    """
    values = _validate_returns(returns)
    _validate_alpha(alpha)
    _validate_finite(var_value)
    if var_value < 0.0:
        raise ValueError("var_value must be non-negative.")

    threshold_return = -var_value
    tail_returns = [value for value in values if value <= threshold_return]
    if not tail_returns:
        return var_value

    tail_losses = [-value for value in tail_returns]
    return sum(tail_losses) / len(tail_losses)


def _historical_var(values: list[float], alpha: float) -> float:
    losses = [-value for value in values]
    losses.sort()
    rank = max(0, min(len(losses) - 1, math.ceil(alpha * len(losses)) - 1))
    # All-positive return windows yield negative loss quantiles; VaR is a loss magnitude.
    return max(0.0, losses[rank])


def _parametric_var(values: list[float], alpha: float) -> float:
    mean_r = sum(values) / len(values)
    std_r = historical_volatility(values)
    z_score = _normal_ppf(1.0 - alpha)
    return -(mean_r + z_score * std_r)


def _normal_ppf(probability: float) -> float:
    """Approximate inverse standard normal CDF."""
    if probability <= 0.0 or probability >= 1.0:
        raise ValueError("probability must be in the open interval (0, 1).")
    if probability == 0.5:
        return 0.0

    if probability < 0.5:
        sign = -1.0
        tail_probability = probability
    else:
        sign = 1.0
        tail_probability = 1.0 - probability

    t = math.sqrt(-2.0 * math.log(tail_probability))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return sign * (
        t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)
    )


def _validate_finite(*values: float) -> None:
    for value in values:
        if not isinstance(value, (int, float)):
            raise TypeError("Numeric values must be int or float.")
        if not math.isfinite(value):
            raise ValueError("Values must be finite (no NaN or inf).")


def _validate_returns(values: Sequence[float], *, name: str = "returns") -> list[float]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be a sequence of floats.")
    if len(values) == 0:
        raise ValueError(f"{name} must not be empty.")

    result: list[float] = []
    for value in values:
        if not isinstance(value, (int, float)):
            raise TypeError(f"{name} must contain only numeric values.")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{name} must not contain NaN or inf.")
        result.append(numeric)
    return result


def _validate_alpha(alpha: float) -> None:
    _validate_finite(alpha)
    if alpha <= 0.0 or alpha >= 1.0:
        raise ValueError("alpha must be in the open interval (0, 1).")


def _validate_weights(weights: Sequence[float]) -> list[float]:
    if len(weights) == 0:
        raise ValueError("weights must not be empty.")
    result: list[float] = []
    for weight in weights:
        _validate_finite(weight)
        result.append(float(weight))
    return result


def _validate_covariance_matrix(
    covariance_matrix: Sequence[Sequence[float]],
    *,
    size: int,
) -> list[list[float]]:
    if len(covariance_matrix) != size:
        raise ValueError("covariance_matrix row count must match weights length.")

    validated: list[list[float]] = []
    for row in covariance_matrix:
        if len(row) != size:
            raise ValueError("covariance_matrix must be square.")
        validated_row: list[float] = []
        for value in row:
            _validate_finite(value)
            validated_row.append(float(value))
        validated.append(validated_row)
    return validated
