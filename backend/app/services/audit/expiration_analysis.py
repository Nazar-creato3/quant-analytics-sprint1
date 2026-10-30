"""Expiration-specific analysis: profit left on the table."""
from __future__ import annotations

from typing import Any

import numpy as np

from app.services.audit.types import ClosedTradeRecord


def compute_expiration_analysis(trades: list[ClosedTradeRecord]) -> dict[str, Any]:
    """Compare peak unrealized P&L vs realized at expiration."""
    expiration_trades = [t for t in trades if t.exit_reason == "expiration"]
    if not expiration_trades:
        return {"expiration_trade_count": 0}

    left_on_table: list[float] = []
    left_pct: list[float] = []
    left_pct_of_realized: list[float] = []
    for trade in expiration_trades:
        peak = trade.peak_unrealized_pnl
        if peak is None:
            continue
        gap = peak - trade.realized_pnl
        left_on_table.append(gap)
        if peak > 0:
            left_pct.append(gap / peak)
        if trade.realized_pnl > 0:
            left_pct_of_realized.append(gap / trade.realized_pnl)

    if not left_on_table:
        return {
            "expiration_trade_count": len(expiration_trades),
            "trades_with_peak_data": 0,
        }

    arr = np.asarray(left_on_table, dtype=float)
    pct_arr = np.asarray(left_pct, dtype=float) if left_pct else np.array([])

    result: dict[str, Any] = {
        "expiration_trade_count": len(expiration_trades),
        "trades_with_peak_data": len(left_on_table),
        "avg_left_on_table_usd": round(float(np.mean(arr)), 2),
        "median_left_on_table_usd": round(float(np.median(arr)), 2),
        "pct_trades_left_profit_on_table": round(
            float(np.mean(arr > 0)), 4
        ),
    }
    if len(pct_arr) > 0:
        result["avg_pct_of_peak_unrealized_left"] = round(float(np.mean(pct_arr)), 4)
    if left_pct_of_realized:
        result["avg_left_on_table_pct_of_realized_profit"] = round(
            float(np.mean(left_pct_of_realized)),
            4,
        )
    return result
