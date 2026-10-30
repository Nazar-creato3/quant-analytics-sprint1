"""Event-driven SMA backtest (Nautilus-style bar loop; no Nautilus catalog required)."""
from __future__ import annotations

from typing import Any, Sequence


def run_event_sma_backtest(
    prices: Sequence[float],
    *,
    fast: int = 10,
    slow: int = 20,
    init_cash: float = 10_000.0,
    fee: float = 0.001,
) -> dict[str, Any]:
    """Long when fast SMA > slow SMA; flatten otherwise. Deterministic fills at close."""
    close = [float(p) for p in prices]
    if len(close) < slow + 2:
        raise ValueError("insufficient prices for event-driven backtest")
    if fast < 1 or slow <= fast:
        raise ValueError("slow must be greater than fast")

    cash = float(init_cash)
    qty = 0.0
    n_trades = 0
    equity = [cash]
    position = 0

    def sma(end: int, window: int) -> float:
        sl = close[end - window + 1 : end + 1]
        return sum(sl) / window

    for i in range(slow - 1, len(close)):
        desired = 1 if sma(i, fast) > sma(i, slow) else 0
        px = close[i]
        if desired != position:
            if position == 1 and qty > 0:
                cash += qty * px * (1.0 - fee)
                qty = 0.0
                n_trades += 1
            if desired == 1:
                qty = (cash * (1.0 - fee)) / px
                cash = 0.0
                n_trades += 1
            position = desired
        mark = cash + qty * px
        equity.append(mark)

    total_return = equity[-1] / init_cash - 1.0 if init_cash else 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)

    return {
        "engine": "event_driven",
        "total_return": float(total_return),
        "max_drawdown": float(max_dd),
        "n_trades": int(n_trades),
        "bars": len(close),
        "equity_end": float(equity[-1]),
        "fast": fast,
        "slow": slow,
        "last_position": int(position),
    }
