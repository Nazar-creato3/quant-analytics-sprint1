"""Return series helpers.

Adapted from ``empyrical.stats.simple_returns`` and ``empyrical.stats.cum_returns_final``
(Apache-2.0, Quantopian empyrical). Pandas/Zipline paths removed; numpy-only.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from app.services.risk.portfolio_math._utils import as_float_array


def simple_returns(closes: Sequence[float]) -> np.ndarray:
    """Simple returns from a price series (empyrical ``simple_returns`` 1-D path)."""
    prices = as_float_array(closes)
    if len(prices) < 2:
        return np.array([], dtype=float)
    prev = prices[:-1]
    mask = prev != 0
    out = np.full(len(prev), np.nan)
    out[mask] = prices[1:][mask] / prev[mask] - 1.0
    return out[np.isfinite(out)]


def cumulative_return(returns: Sequence[float]) -> float | None:
    """Total return from simple returns (empyrical ``cum_returns_final``, starting_value=0)."""
    arr = as_float_array(returns)
    if arr.size == 0:
        return None
    return float(np.prod(1.0 + arr) - 1.0)
