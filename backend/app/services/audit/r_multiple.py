"""R-multiple analysis for position audit."""
from __future__ import annotations

from typing import Any

import numpy as np

from app.services.audit.types import ClosedTradeRecord


def _initial_risk_dollars(trade: ClosedTradeRecord) -> float | None:
    if trade.stop_loss_price is None:
        return None
    if trade.entry_price <= 0 or trade.position_size_usd <= 0:
        return None
    qty = trade.position_size_usd / trade.entry_price
    risk_per_share = abs(trade.entry_price - trade.stop_loss_price)
    if risk_per_share <= 0:
        return None
    return risk_per_share * qty


def compute_r_multiple(trade: ClosedTradeRecord) -> float | None:
    """R = realized_pnl / initial_risk_dollars."""
    risk = _initial_risk_dollars(trade)
    if risk is None or risk <= 0:
        return None
    return trade.realized_pnl / risk


def compute_r_multiple_stats(trades: list[ClosedTradeRecord]) -> dict[str, Any]:
    """Distribution stats for R-multiples across closed trades."""
    values = [r for t in trades if (r := compute_r_multiple(t)) is not None]
    if not values:
        return {"count": 0, "mean_r": None, "pct_r_above_2": None, "pct_r_below_minus_1": None}

    arr = np.asarray(values, dtype=float)
    return {
        "count": len(values),
        "mean_r": round(float(np.mean(arr)), 4),
        "median_r": round(float(np.median(arr)), 4),
        "std_r": round(float(np.std(arr, ddof=1)), 4) if len(arr) > 1 else 0.0,
        "pct_r_above_2": round(float(np.mean(arr > 2.0)), 4),
        "pct_r_below_minus_1": round(float(np.mean(arr < -1.0)), 4),
        "distribution": {
            "min": round(float(np.min(arr)), 4),
            "p25": round(float(np.percentile(arr, 25)), 4),
            "p75": round(float(np.percentile(arr, 75)), 4),
            "max": round(float(np.max(arr)), 4),
        },
    }
