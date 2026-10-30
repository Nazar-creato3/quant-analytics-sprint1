"""VectorBT momentum backtest adapter — optional dependency."""
from __future__ import annotations

from typing import Any, Sequence


def run_vectorbt_momentum(prices: Sequence[float], *, lookback: int = 10) -> dict[str, Any]:
    """Fast SMA crossover backtest via vectorbt; raises ImportError if missing."""
    from app.services.trading_engines.probes import _patch_plotly_templates_for_vectorbt

    _patch_plotly_templates_for_vectorbt()
    import numpy as np
    import vectorbt as vbt

    close = np.array([float(p) for p in prices], dtype=float)
    if len(close) < lookback + 5:
        raise ValueError("insufficient prices for vectorbt backtest")

    fast = vbt.MA.run(close, lookback)
    slow = vbt.MA.run(close, lookback * 2)
    entries = fast.ma_crossed_above(slow.ma)
    exits = fast.ma_crossed_below(slow.ma)
    pf = vbt.Portfolio.from_signals(close, entries, exits, init_cash=10_000.0, fees=0.001)
    return {
        "engine": "vectorbt",
        "total_return": float(pf.total_return()),
        "sharpe": float(pf.sharpe_ratio()) if pf.sharpe_ratio() == pf.sharpe_ratio() else None,
        "max_drawdown": float(pf.max_drawdown()),
        "n_trades": int(pf.trades.count()),
        "bars": len(close),
    }
