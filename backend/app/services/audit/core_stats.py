"""Core performance statistics for position audit."""
from __future__ import annotations

from typing import Any

import numpy as np

from app.services.audit.types import ClosedTradeRecord
from app.services.terminal_platform.quant.metrics import (
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
)


def compute_core_stats(trades: list[ClosedTradeRecord]) -> dict[str, Any]:
    """Win rate, expectancy, profit factor, Sharpe/Sortino/DD on trade returns."""
    if not trades:
        return {}

    pnls = [t.realized_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n = len(pnls)
    win_rate = len(wins) / n if n else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    expectancy = (win_rate * avg_win) + ((1.0 - win_rate) * avg_loss)

    returns = [t.return_pct for t in trades]
    equity = np.cumprod(1.0 + np.asarray(returns, dtype=float))
    equity = np.insert(equity, 0, 1.0)
    dd = max_drawdown(equity.tolist())

    sharpe = sharpe_ratio(returns, periods_per_year=252) if len(returns) >= 2 else 0.0
    sortino = sortino_ratio(returns, periods_per_year=252) if len(returns) >= 2 else 0.0
    cagr_proxy = float(np.prod(1.0 + np.asarray(returns)) - 1.0) if returns else 0.0
    calmar = cagr_proxy / dd if dd > 1e-9 else 0.0

    return {
        "trade_count": n,
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "payoff_ratio": round(payoff, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else None,
        "expectancy": round(expectancy, 2),
        "total_pnl": round(sum(pnls), 2),
        "max_drawdown": round(dd, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
    }
