"""Multi-factor OLS regression utilities for FactorEngine."""
from __future__ import annotations

from typing import Sequence

from app.services.factor.types import ALL_FACTORS, FactorName, RollingFactorModelResult


def ols_multivariate(
    y: Sequence[float],
    factor_matrix: Sequence[Sequence[float]],
    *,
    factor_names: Sequence[FactorName] | None = None,
) -> tuple[dict[FactorName, float], float]:
    """Fit ``y ~ X`` via ordinary least squares and return betas plus R².

    ``factor_matrix`` rows align with ``y``; columns are factor return series.
    An intercept is included automatically.
    """
    names = list(factor_names or ALL_FACTORS)
    y_values = _as_1d(y, name="y")
    x_values = _as_2d(factor_matrix, expected_rows=len(y_values), name="factor_matrix")
    if len(x_values[0]) != len(names):
        raise ValueError("factor_matrix column count must match factor_names length.")

    design = [[1.0, *row] for row in x_values]
    beta_vector = _solve_least_squares(design, y_values)
    betas = {name: beta_vector[index + 1] for index, name in enumerate(names)}

    y_hat = [_dot(row, beta_vector) for row in design]
    ss_res = sum((actual - predicted) ** 2 for actual, predicted in zip(y_values, y_hat))
    mean_y = sum(y_values) / len(y_values)
    ss_tot = sum((value - mean_y) ** 2 for value in y_values)
    r_squared = 0.0 if ss_tot == 0.0 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
    return betas, r_squared


def rolling_factor_regression(
    instrument_returns: Sequence[float],
    factor_returns: dict[FactorName, Sequence[float]],
    *,
    window: int,
    min_observations: int | None = None,
) -> list[RollingFactorModelResult]:
    """Re-estimate factor betas on each rolling window ending at index ``t``."""
    if window < 2:
        raise ValueError("window must be >= 2.")
    min_obs = min_observations or window
    y = _as_1d(instrument_returns, name="instrument_returns")
    n = len(y)
    if n == 0:
        return []

    names = list(factor_returns.keys())
    columns = [_as_1d(factor_returns[name], name=name.value) for name in names]
    if any(len(column) != n for column in columns):
        raise ValueError("All factor return series must match instrument return length.")

    results: list[RollingFactorModelResult] = []
    for end in range(window - 1, n):
        start = end - window + 1
        window_y = y[start : end + 1]
        window_x = [[column[index] for column in columns] for index in range(start, end + 1)]
        if len(window_y) < min_obs:
            continue
        if _is_degenerate(window_y, window_x):
            continue
        betas, r_squared = ols_multivariate(window_y, window_x, factor_names=names)
        results.append(
            RollingFactorModelResult(
                time_index=end,
                betas=betas,
                r_squared=r_squared,
            )
        )
    return results


def _as_1d(values: Sequence[float], *, name: str) -> list[float]:
    if len(values) == 0:
        raise ValueError(f"{name} must not be empty.")
    result: list[float] = []
    for value in values:
        numeric = float(value)
        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            raise ValueError(f"{name} must not contain NaN or inf.")
        result.append(numeric)
    return result


def _as_2d(values: Sequence[Sequence[float]], *, expected_rows: int, name: str) -> list[list[float]]:
    rows: list[list[float]] = []
    for row in values:
        rows.append(_as_1d(row, name=name))
    if len(rows) != expected_rows:
        raise ValueError(f"{name} row count must match dependent variable length.")
    return rows


def _is_degenerate(y: Sequence[float], x: Sequence[Sequence[float]]) -> bool:
    if _std(y) == 0.0:
        return True
    if not x:
        return True
    column_count = len(x[0])
    for column_index in range(column_count):
        column = [row[column_index] for row in x]
        if _std(column) != 0.0:
            return False
    return True


def _std(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean_value = sum(values) / len(values)
    variance = sum((value - mean_value) ** 2 for value in values) / max(len(values) - 1, 1)
    return variance ** 0.5


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _transpose(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    if not matrix:
        return []
    return [list(column) for column in zip(*matrix)]


def _matmul(left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]) -> list[list[float]]:
    right_t = _transpose(right)
    return [[_dot(row, col) for col in right_t] for row in left]


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for pivot in range(size):
        pivot_row = max(range(pivot, size), key=lambda row: abs(augmented[row][pivot]))
        if abs(augmented[pivot_row][pivot]) < 1e-12:
            raise ValueError("Singular matrix in OLS solve.")
        if pivot_row != pivot:
            augmented[pivot], augmented[pivot_row] = augmented[pivot_row], augmented[pivot]
        pivot_value = augmented[pivot][pivot]
        for column in range(pivot, size + 1):
            augmented[pivot][column] /= pivot_value
        for row in range(size):
            if row == pivot:
                continue
            factor = augmented[row][pivot]
            if factor == 0.0:
                continue
            for column in range(pivot, size + 1):
                augmented[row][column] -= factor * augmented[pivot][column]
    return [augmented[index][size] for index in range(size)]


def _solve_least_squares(design: Sequence[Sequence[float]], y: Sequence[float]) -> list[float]:
    x_t = _transpose(design)
    xtx = _matmul(x_t, design)
    xty = [_dot(x_t[row], y) for row in range(len(x_t))]
    try:
        return _solve_linear_system(xtx, xty)
    except ValueError:
        return _solve_least_squares_pseudoinverse(design, y)


def _solve_least_squares_pseudoinverse(design: Sequence[Sequence[float]], y: Sequence[float]) -> list[float]:
    """Fallback path for rank-deficient designs."""
    x_t = _transpose(design)
    xtx = _matmul(x_t, design)
    ridge = 1e-8
    regularized = [
        [xtx[row][column] + (ridge if row == column else 0.0) for column in range(len(xtx))]
        for row in range(len(xtx))
    ]
    xty = [_dot(x_t[row], y) for row in range(len(x_t))]
    return _solve_linear_system(regularized, xty)
