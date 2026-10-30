"""Triple-barrier labeling for forecast targets (López de Prado).

Labels each bar by which barrier is touched first: upper (+k×ATR take-profit),
lower (−k×ATR stop-loss), or vertical (max holding period expiry).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Sequence

import numpy as np


class BarrierOutcome(IntEnum):
    UPPER = 1
    LOWER = -1
    VERTICAL = 0


@dataclass(frozen=True, slots=True)
class TripleBarrierConfig:
    atr_multiplier: float = 1.5
    max_holding_days: int = 10
    atr_window: int = 14


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, window: int) -> np.ndarray:
    n = len(closes)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    tr[0] = highs[0] - lows[0]
    atr = np.full(n, np.nan)
    if n >= window:
        atr[window - 1] = np.mean(tr[:window])
        for i in range(window, n):
            atr[i] = (atr[i - 1] * (window - 1) + tr[i]) / window
    return atr


def triple_barrier_labels(
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    config: TripleBarrierConfig | None = None,
) -> list[int]:
    """Return directional labels (+1/−1/0) from triple-barrier events."""
    cfg = config or TripleBarrierConfig()
    c = np.asarray(closes, dtype=float)
    n = len(c)
    if n < cfg.atr_window + cfg.max_holding_days + 5:
        return [0] * n

    h = np.asarray(highs if highs is not None else c, dtype=float)
    l = np.asarray(lows if lows is not None else c, dtype=float)
    atr = _atr(h, l, c, cfg.atr_window)

    labels = [0] * n
    for i in range(cfg.atr_window, n - 1):
        if np.isnan(atr[i]) or atr[i] <= 0:
            continue
        entry = c[i]
        upper = entry + cfg.atr_multiplier * atr[i]
        lower = entry - cfg.atr_multiplier * atr[i]
        outcome = BarrierOutcome.VERTICAL
        end = min(i + cfg.max_holding_days + 1, n)
        for j in range(i + 1, end):
            if h[j] >= upper:
                outcome = BarrierOutcome.UPPER
                break
            if l[j] <= lower:
                outcome = BarrierOutcome.LOWER
                break
        labels[i] = int(outcome)
    return labels


def labels_to_signs(labels: Sequence[int]) -> list[int]:
    """Map barrier outcomes to directional signs for classification."""
    return [int(v) for v in labels]
