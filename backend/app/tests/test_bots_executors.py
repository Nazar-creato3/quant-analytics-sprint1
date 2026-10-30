"""Unit tests for DCA/momentum executors — no FastAPI/DB deps."""
from __future__ import annotations

from app.services.bots.dca import apply_dca_tick, new_runtime
from app.services.bots.momentum import apply_momentum_tick, new_runtime as mom_runtime


def test_dca_first_buy_and_dip():
    data = {
        "config": {
            "ticker": "TEST",
            "total_capital": 5000,
            "order_size_usd": 500,
            "max_entries": 5,
            "interval_ticks": 3,
            "dip_pct": 0.02,
            "take_profit_pct": 0.05,
            "entry_price": 100.0,
        },
        "runtime": new_runtime(100.0),
        "realized_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
        "is_paused": False,
    }
    data = apply_dca_tick(data, 100.0, bot_id="t1")
    assert data["runtime"]["entries_count"] == 1
    data = apply_dca_tick(data, 97.0, bot_id="t1")
    assert data["runtime"]["entries_count"] >= 1


def test_momentum_enters_on_uptrend():
    data = {
        "config": {
            "ticker": "TEST",
            "total_capital": 10_000,
            "position_size_pct": 0.5,
            "lookback_ticks": 5,
            "entry_momentum_pct": 0.01,
            "take_profit_pct": 0.06,
            "stop_loss_pct": 0.04,
            "entry_price": 100.0,
        },
        "runtime": mom_runtime(100.0),
        "realized_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
        "is_paused": False,
    }
    for p in [100, 101, 102, 103, 104, 106]:
        data = apply_momentum_tick(data, float(p), bot_id="t1")
    assert float(data["runtime"]["position_qty"]) > 0
