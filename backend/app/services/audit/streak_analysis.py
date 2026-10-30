"""Streak and Monte Carlo bust analysis."""
from __future__ import annotations

from typing import Any

import numpy as np

from app.services.audit.types import ClosedTradeRecord


def _longest_streak(pnls: list[float], *, wins: bool) -> int:
    best = 0
    current = 0
    for p in pnls:
        is_win = p > 0
        if is_win == wins:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def compute_streak_analysis(trades: list[ClosedTradeRecord]) -> dict[str, Any]:
    pnls = [t.realized_pnl for t in trades]
    return {
        "longest_winning_streak": _longest_streak(pnls, wins=True),
        "longest_losing_streak": _longest_streak(pnls, wins=False),
    }


def compute_monte_carlo_bust(
    trades: list[ClosedTradeRecord],
    *,
    simulations: int = 2000,
    bust_threshold: float = 0.25,
) -> dict[str, Any]:
    """Estimate bust probability via random reorderings of trade returns."""
    returns = [t.return_pct for t in trades]
    if len(returns) < 2:
        return {"simulations": 0, "bust_probability": None}

    bust_count = 0
    rng = np.random.default_rng(42)
    arr = np.asarray(returns, dtype=float)

    for _ in range(simulations):
        shuffled = rng.permutation(arr)
        equity = np.cumprod(1.0 + shuffled)
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / np.maximum(peak, 1e-12)
        if float(np.max(dd)) >= bust_threshold:
            bust_count += 1

    return {
        "simulations": simulations,
        "bust_threshold_drawdown": bust_threshold,
        "bust_probability": round(bust_count / simulations, 4),
    }
