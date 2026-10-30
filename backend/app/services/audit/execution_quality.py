"""Execution quality (TCA-lite): signal-to-fill slippage."""
from __future__ import annotations

from typing import Any

import numpy as np

from app.services.audit.types import ClosedTradeRecord


def _slippage(trade: ClosedTradeRecord) -> float | None:
    signal = trade.signal_generated_price
    fill = trade.fill_price or trade.entry_price
    if signal is None or fill is None or signal <= 0:
        return None
    sign = -1.0 if trade.direction.lower() == "short" else 1.0
    return sign * (fill - signal)


def compute_execution_quality(trades: list[ClosedTradeRecord]) -> dict[str, Any]:
    """Aggregate signal-to-fill slippage per trade."""
    values = [s for t in trades if (s := _slippage(t)) is not None]
    if not values:
        return {"count": 0, "mean_slippage": None}

    arr = np.asarray(values, dtype=float)
    return {
        "count": len(values),
        "mean_slippage": round(float(np.mean(arr)), 4),
        "median_slippage": round(float(np.median(arr)), 4),
        "std_slippage": round(float(np.std(arr, ddof=1)), 4) if len(arr) > 1 else 0.0,
        "pct_adverse_slippage": round(float(np.mean(arr > 0)), 4),
        "distribution": {
            "min": round(float(np.min(arr)), 4),
            "max": round(float(np.max(arr)), 4),
        },
    }
