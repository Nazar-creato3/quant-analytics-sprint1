"""Drawdown metrics.

Adapted from ``empyrical.stats.max_drawdown`` (Apache-2.0, Quantopian empyrical).
Uses cumulative wealth from simple returns; Zipline/pandas branches removed.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from app.services.risk.portfolio_math._utils import as_float_array


def max_drawdown(returns: Sequence[float]) -> float | None:
    """Maximum drawdown as a negative fraction (empyrical-equivalent ratio)."""
    arr = as_float_array(returns)
    if arr.size == 0:
        return None

    equity = np.cumprod(1.0 + arr)
    peak = np.maximum.accumulate(equity)
    drawdowns = equity / peak - 1.0
    return float(drawdowns.min())
