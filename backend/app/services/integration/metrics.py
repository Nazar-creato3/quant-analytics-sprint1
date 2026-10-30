"""Performance metrics for validation replay reports."""
from __future__ import annotations

import math
from typing import Sequence

from app.services.integration.types import PaperTrade


def compute_win_rate(trades: Sequence[PaperTrade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for trade in trades if trade.return_pct > 0)
    return round(wins / len(trades), 4)


def compute_max_drawdown_pct(equity_curve: Sequence[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak * 100.0
            max_dd = max(max_dd, dd)
    return round(max_dd, 4)


def compute_sharpe_ratio(returns: Sequence[float], *, risk_free_rate: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    excess = [value - risk_free_rate for value in returns]
    mean = sum(excess) / len(excess)
    variance = sum((value - mean) ** 2 for value in excess) / (len(excess) - 1)
    std = math.sqrt(variance)
    if std <= 1e-12:
        return 0.0
    return round(mean / std * math.sqrt(252), 4)


def build_equity_curve(
    trades: Sequence[PaperTrade],
    *,
    initial_capital: float = 100_000.0,
) -> tuple[list[float], list[float]]:
    """Return equity curve and per-trade return fractions."""
    equity = initial_capital
    curve = [equity]
    returns: list[float] = []
    for trade in trades:
        ret = trade.return_pct / 100.0
        equity *= 1.0 + ret
        curve.append(equity)
        returns.append(ret)
    return curve, returns
