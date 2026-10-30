"""Cross-sectional relative ranking within sector (vs absolute direction)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class CrossSectionalRank:
    symbol: str
    sector: str
    rank: int
    percentile: float
    expected_relative_return: float
    outperforms_sector: bool


@dataclass(frozen=True, slots=True)
class CrossSectionalAccuracy:
    accuracy: float
    n: int
    absolute_accuracy: float
    absolute_n: int


def _forward_return(prices: Sequence[float], horizon: int) -> float | None:
    if len(prices) <= horizon:
        return None
    start, end = prices[-(horizon + 1)], prices[-1]
    if start <= 0:
        return None
    return (end - start) / start


def rank_sector_peers(
    sector_returns: Mapping[str, float],
    *,
    sector: str,
) -> list[CrossSectionalRank]:
    """Rank tickers by expected relative return within a sector."""
    if not sector_returns:
        return []
    symbols = sorted(sector_returns.keys())
    values = [sector_returns[s] for s in symbols]
    order = np.argsort(values)[::-1]
    n = len(symbols)
    results: list[CrossSectionalRank] = []
    for rank_idx, sym_idx in enumerate(order):
        sym = symbols[sym_idx]
        ret = values[sym_idx]
        median = float(np.median(values))
        results.append(
            CrossSectionalRank(
                symbol=sym,
                sector=sector,
                rank=rank_idx + 1,
                percentile=round(1.0 - rank_idx / max(n - 1, 1), 4),
                expected_relative_return=ret - median,
                outperforms_sector=ret > median,
            )
        )
    return results


def evaluate_cross_sectional_vs_absolute(
    sector_price_histories: Mapping[str, Sequence[float]],
    predictor_fn,
    *,
    horizon: int = 10,
    min_history: int = 30,
) -> CrossSectionalAccuracy:
    """Compare cross-sectional ranking accuracy vs absolute direction on same window."""
    symbols = list(sector_price_histories.keys())
    if len(symbols) < 2:
        return CrossSectionalAccuracy(0.5, 0, 0.5, 0)

    min_len = min(len(sector_price_histories[s]) for s in symbols)
    if min_len < min_history + horizon + 5:
        return CrossSectionalAccuracy(0.5, 0, 0.5, 0)

    cs_hits = cs_total = abs_hits = abs_total = 0
    for i in range(min_history, min_len - horizon):
        expected: dict[str, float] = {}
        for sym in symbols:
            hist = list(sector_price_histories[sym][: i + 1])
            try:
                expected[sym] = predictor_fn(hist)
            except Exception:
                expected[sym] = 0.0

        ranks = rank_sector_peers(expected, sector="peer_group")
        top = ranks[0].symbol if ranks else None
        bottom = ranks[-1].symbol if ranks else None

        realized: dict[str, float] = {}
        for sym in symbols:
            ret = _forward_return(
                sector_price_histories[sym][i : i + horizon + 1],
                horizon,
            )
            if ret is not None:
                realized[sym] = ret

        if len(realized) < 2 or top is None or bottom is None:
            continue

        best_sym = max(realized, key=realized.get)  # type: ignore[arg-type]
        worst_sym = min(realized, key=realized.get)  # type: ignore[arg-type]
        cs_total += 1
        if top == best_sym or bottom == worst_sym:
            cs_hits += 1

        for sym in symbols:
            if sym not in realized:
                continue
            pred_sign = 1 if expected[sym] > 0 else (-1 if expected[sym] < 0 else 0)
            act_sign = 1 if realized[sym] > 0 else (-1 if realized[sym] < 0 else 0)
            if pred_sign == 0 or act_sign == 0:
                continue
            abs_total += 1
            if pred_sign == act_sign:
                abs_hits += 1

    return CrossSectionalAccuracy(
        accuracy=cs_hits / cs_total if cs_total else 0.5,
        n=cs_total,
        absolute_accuracy=abs_hits / abs_total if abs_total else 0.5,
        absolute_n=abs_total,
    )
