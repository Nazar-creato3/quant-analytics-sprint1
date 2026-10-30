"""Value-at-risk and expected shortfall.

Adapted from ``empyrical.stats.value_at_risk`` and
``empyrical.stats.conditional_value_at_risk`` (Apache-2.0, Quantopian empyrical).

Apex reports VaR/ES as positive loss magnitudes for portfolio UI; upstream
empyrical returns signed return quantiles (typically negative for tail losses).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from app.services.risk.portfolio_math._utils import as_float_array

MIN_OBSERVATIONS = 40


def historical_var_quantile(returns: Sequence[float], cutoff: float = 0.05) -> float | None:
    """Empirical return quantile at ``cutoff`` (matches empyrical ``value_at_risk``)."""
    values = as_float_array(returns)
    if values.size < MIN_OBSERVATIONS:
        return None
    return float(np.percentile(values, 100.0 * cutoff))


def conditional_var_quantile(returns: Sequence[float], cutoff: float = 0.05) -> float | None:
    """Mean of worst ``cutoff`` fraction of returns (matches empyrical CVaR)."""
    values = as_float_array(returns)
    if values.size < MIN_OBSERVATIONS:
        return None
    cutoff_index = int((values.size - 1) * cutoff)
    partitioned = np.partition(values.copy(), cutoff_index)
    return float(np.mean(partitioned[: cutoff_index + 1]))


def historical_var_es(
    port_returns: Sequence[float],
    *,
    min_observations: int = MIN_OBSERVATIONS,
) -> tuple[float | None, float | None, float | None]:
    """Historical VaR 95/99 and ES 95 as positive loss fractions."""
    values = as_float_array(port_returns)
    if values.size < min_observations:
        return None, None, None

    q05 = historical_var_quantile(values, cutoff=0.05)
    q01 = historical_var_quantile(values, cutoff=0.01)
    if q05 is None or q01 is None:
        return None, None, None

    var95 = max(0.0, -q05)
    var99 = max(0.0, -q01)
    cvar_q05 = conditional_var_quantile(values, cutoff=0.05)
    es95 = max(0.0, -cvar_q05) if cvar_q05 is not None else var95
    if var99 < var95:
        var99 = var95
    return var95, var99, es95
