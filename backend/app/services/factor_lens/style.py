"""Long-short style factors: monthly tertiles, equal weights (R10)."""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np


def _tertile_masks(values: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(values, dtype=float)
    valid = np.isfinite(arr)
    if int(valid.sum()) < 6:
        return np.zeros(arr.size, dtype=bool), np.zeros(arr.size, dtype=bool)
    q1, q2 = np.nanquantile(arr, [1 / 3, 2 / 3])
    low = valid & (arr <= q1)
    high = valid & (arr >= q2)
    return high, low


def long_short_return(
    asset_returns: Mapping[str, float],
    characteristic: Mapping[str, float],
    *,
    high_minus_low: bool = True,
) -> float | None:
    names = [n for n in asset_returns if n in characteristic]
    if len(names) < 6:
        return None
    highs, lows = _tertile_masks([characteristic[n] for n in names])
    high_names = [n for n, flag in zip(names, highs, strict=True) if flag]
    low_names = [n for n, flag in zip(names, lows, strict=True) if flag]
    if not high_names or not low_names:
        return None
    high = float(np.mean([asset_returns[n] for n in high_names]))
    low = float(np.mean([asset_returns[n] for n in low_names]))
    return high - low if high_minus_low else low - high


def momentum_12_1(history: Sequence[float]) -> float | None:
    """12-month return excluding the last month (~21 days)."""
    if len(history) < 252:
        return None
    window = history[-252:-21]
    if not window:
        return None
    equity = 1.0
    for r in window:
        equity *= 1.0 + float(r)
    return equity - 1.0
