"""Factor attribution for position audit."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.audit.types import ClosedTradeRecord


def _dominant_factor(exposures: dict[str, float]) -> str:
    if not exposures:
        return "unknown"
    return max(exposures.items(), key=lambda kv: abs(kv[1]))[0]


def _group_stats(trades: list[ClosedTradeRecord]) -> dict[str, Any]:
    if not trades:
        return {"count": 0, "win_rate": 0.0, "expectancy": 0.0, "total_pnl": 0.0}
    pnls = [t.realized_pnl for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    n = len(trades)
    win_rate = wins / n
    avg_win = sum(p for p in pnls if p > 0) / wins if wins else 0.0
    loss_count = n - wins
    avg_loss = sum(p for p in pnls if p <= 0) / loss_count if loss_count else 0.0
    expectancy = win_rate * avg_win + (1.0 - win_rate) * avg_loss
    return {
        "count": n,
        "win_rate": round(win_rate, 4),
        "expectancy": round(expectancy, 2),
        "total_pnl": round(sum(pnls), 2),
    }


def compute_factor_attribution(trades: list[ClosedTradeRecord]) -> dict[str, Any]:
    """Group trades by dominant factor exposure at entry."""
    groups: dict[str, list[ClosedTradeRecord]] = defaultdict(list)
    for trade in trades:
        groups[_dominant_factor(trade.factor_exposures)].append(trade)

    by_factor = {factor: _group_stats(items) for factor, items in sorted(groups.items())}
    return {
        "by_dominant_factor": by_factor,
        "factor_count": len(by_factor),
    }
