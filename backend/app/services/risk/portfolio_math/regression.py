"""Factor regression helpers.

Daily OLS alpha/beta: same intercept + slope structure as empyrical's linear
regression against a benchmark, but returns daily alpha (not annualized).

Multi-factor betas: OLS of portfolio returns on factor columns — same linear
structure used in pyfolio/empyrical performance attribution, without pandas
position/loadings preprocessing (Apex supplies aligned factor return series).
"""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from app.services.risk.portfolio_math._utils import as_float_array
from app.services.risk.portfolio_math.var import MIN_OBSERVATIONS


def ols_alpha_beta(
    port_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    *,
    min_observations: int = MIN_OBSERVATIONS,
) -> tuple[float | None, float | None, float | None]:
    """Daily alpha, beta, and R² from OLS: r_p = α + β·r_b + ε."""
    y = as_float_array(port_returns)
    x = as_float_array(benchmark_returns)
    n = min(len(y), len(x))
    if n < min_observations:
        return None, None, None
    y = y[-n:]
    x = x[-n:]
    design = np.column_stack([np.ones(n), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    alpha_d, beta = float(coef[0]), float(coef[1])
    fitted = design @ coef
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return alpha_d, beta, r2


def multi_factor_betas(
    port_returns: Sequence[float],
    factor_returns: Mapping[str, Sequence[float]],
    *,
    min_observations: int = MIN_OBSERVATIONS,
) -> dict[str, float]:
    """OLS betas of portfolio returns on supplied factor series."""
    y = as_float_array(port_returns)
    names = [k for k, v in factor_returns.items() if len(v) >= min_observations]
    if not names or len(y) < min_observations:
        return {}

    cols: list[np.ndarray] = []
    n = len(y)
    for name in names:
        col = as_float_array(factor_returns[name])
        n = min(n, len(col))
        cols.append(col)
    if n < min_observations:
        return {}

    y = y[-n:]
    x = np.column_stack([c[-n:] for c in cols])
    design = np.column_stack([np.ones(n), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    return {name: float(coef[i + 1]) for i, name in enumerate(names)}
