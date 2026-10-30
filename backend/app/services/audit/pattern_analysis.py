"""Pattern analysis: ticker, sector, regime, day-of-week, hold duration."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.audit.types import ClosedTradeRecord


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


def _hold_duration_bucket(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    days = seconds / 86_400.0
    if days < 1:
        return "<1d"
    if days < 3:
        return "1-3d"
    if days < 7:
        return "3-7d"
    if days < 14:
        return "7-14d"
    return "14d+"


def _day_of_week(dt: Any) -> str:
    if dt is None:
        return "unknown"
    return dt.strftime("%A")


def compute_pattern_analysis(trades: list[ClosedTradeRecord]) -> dict[str, Any]:
    """Break down win rate and expectancy by pattern dimensions."""
    by_ticker: dict[str, list[ClosedTradeRecord]] = defaultdict(list)
    by_sector: dict[str, list[ClosedTradeRecord]] = defaultdict(list)
    by_regime: dict[str, list[ClosedTradeRecord]] = defaultdict(list)
    by_dow: dict[str, list[ClosedTradeRecord]] = defaultdict(list)
    by_hold: dict[str, list[ClosedTradeRecord]] = defaultdict(list)

    for trade in trades:
        by_ticker[trade.ticker].append(trade)
        by_sector[trade.sector_at_entry or "unknown"].append(trade)
        by_regime[trade.regime_at_entry or "unknown"].append(trade)
        by_dow[_day_of_week(trade.filled_at)].append(trade)
        by_hold[_hold_duration_bucket(trade.hold_duration_seconds)].append(trade)

    return {
        "by_ticker": {k: _group_stats(v) for k, v in sorted(by_ticker.items())},
        "by_sector": {k: _group_stats(v) for k, v in sorted(by_sector.items())},
        "by_regime": {k: _group_stats(v) for k, v in sorted(by_regime.items())},
        "by_day_of_week": {k: _group_stats(v) for k, v in sorted(by_dow.items())},
        "by_hold_duration": {k: _group_stats(v) for k, v in sorted(by_hold.items())},
    }
