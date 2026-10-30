"""Tests for shared bot risk module (correlation + circuit breaker + sizing)."""
from __future__ import annotations

import pytest

from app.services.bot_risk.guard import BotRiskGuard, BotRiskConfig
from app.services.bot_risk.grid_actions import enforce_grid_stop_loss
from app.services.bot_risk.portfolio import build_bot_refs, build_portfolio_snapshot
from app.services.bot_risk.position_sizing import compute_risk_based_size
from app.services.bot_risk.types import CorrelationMode
from app.services.bots.dca import apply_dca_tick, new_runtime
from app.services.bots.momentum import apply_momentum_tick, new_runtime as mom_runtime


def _dca_bot(
    bot_id: str,
    ticker: str,
    *,
    with_position: bool = False,
    total_pnl: float = 0.0,
) -> dict:
    runtime = new_runtime(100.0)
    if with_position:
        runtime.update({
            "position_qty": 1.0,
            "avg_entry": 100.0,
            "entries_count": 1,
            "deployed_usd": 100.0,
            "executor_state": "accumulating",
        })
    return {
        "config": {
            "ticker": ticker,
            "total_capital": 5000,
            "order_size_usd": 500,
            "max_entries": 5,
            "interval_ticks": 1,
            "dip_pct": 0.02,
            "take_profit_pct": 0.5,
            "entry_price": 100.0,
        },
        "runtime": runtime,
        "realized_pnl": 0.0,
        "total_pnl": total_pnl,
        "total_trades": 0,
        "is_active": True,
        "is_paused": False,
    }


def _momentum_bot(bot_id: str, ticker: str, *, total_pnl: float = 0.0) -> dict:
    return {
        "config": {
            "ticker": ticker,
            "total_capital": 10_000,
            "position_size_pct": 0.5,
            "lookback_ticks": 3,
            "entry_momentum_pct": 0.01,
            "take_profit_pct": 0.5,
            "stop_loss_pct": 0.04,
            "entry_price": 100.0,
        },
        "runtime": mom_runtime(100.0),
        "realized_pnl": 0.0,
        "total_pnl": total_pnl,
        "total_trades": 0,
        "is_active": True,
        "is_paused": False,
    }


def test_position_sizing_from_stop_distance():
    result = compute_risk_based_size(
        portfolio_usd=10_000,
        entry_price=100.0,
        stop_loss_price=95.0,
        risk_pct=2.0,
        max_position_pct=10.0,
    )
    assert result.allowed
    # 2% of 10k = $200 risk; $5/share -> 40 shares -> $4000 notional, capped at 10% = $1000
    assert result.notional_usd == 1000.0
    assert result.quantity == 10.0


def test_correlation_blocks_second_bot_on_same_instrument():
    guard = BotRiskGuard(
        BotRiskConfig(
            risk_per_trade_pct=1.5,
            circuit_breaker_drawdown_pct=10.0,
            correlation_mode=CorrelationMode.BLOCK,
            default_stop_loss_pct=0.05,
            max_position_pct=10.0,
        )
    )
    refs = build_bot_refs(
        dca={"dca-1": _dca_bot("dca-1", "BTC/USDT", with_position=True)},
    )
    snapshot = build_portfolio_snapshot(refs)

    corr = guard.check_correlation(
        ticker="BTCUSDT",
        snapshot=snapshot,
        exclude_bot_id="mom-1",
    )
    assert not corr.allowed
    assert "dca-1" in corr.conflicting_bots[0]


def test_two_bots_correlation_blocks_momentum_entry():
    guard = BotRiskGuard(
        BotRiskConfig(
            risk_per_trade_pct=2.0,
            circuit_breaker_drawdown_pct=10.0,
            correlation_mode=CorrelationMode.BLOCK,
            default_stop_loss_pct=0.05,
            max_position_pct=50.0,
        )
    )
    dca_data = _dca_bot("dca-1", "ETH/USD", with_position=True)
    mom_data = _momentum_bot("mom-1", "ETHUSD")
    refs = build_bot_refs(dca={"dca-1": dca_data}, momentum={"mom-1": mom_data})
    snapshot = build_portfolio_snapshot(refs)

    for p in [100, 101, 102, 103, 104, 106]:
        mom_data = apply_momentum_tick(
            mom_data, float(p), bot_id="mom-1", risk_snapshot=snapshot
        )

    assert float(mom_data["runtime"]["position_qty"]) == 0.0
    events = [e["type"] for e in mom_data.get("recent_events") or []]
    assert "risk_block" in events


def test_circuit_breaker_halts_all_bots_on_drawdown():
    guard = BotRiskGuard(
        BotRiskConfig(
            risk_per_trade_pct=1.5,
            circuit_breaker_drawdown_pct=5.0,
            correlation_mode=CorrelationMode.BLOCK,
            default_stop_loss_pct=0.05,
            max_position_pct=10.0,
        )
    )
    dca = _dca_bot("dca-1", "BTC/USDT", total_pnl=-600.0)
    mom = _momentum_bot("mom-1", "SOL/USDT", total_pnl=-200.0)
    refs = build_bot_refs(dca={"dca-1": dca}, momentum={"mom-1": mom})
    snapshot = build_portfolio_snapshot(refs, peak_pnl=0.0)

    result = guard.evaluate_circuit_breaker(snapshot)
    assert result.tripped
    assert result.drawdown_pct >= 5.0

    halted = guard.apply_portfolio_halt(refs, reason=result.reason)
    assert halted == 2
    assert dca["is_paused"] and dca["risk_halt"]
    assert mom["is_paused"] and mom["risk_halt"]


def test_grid_stop_loss_flattens_and_halts():
    data = {
        "config": {
            "ticker": "BTC/USDT",
            "lower_price": 90.0,
            "upper_price": 110.0,
            "stop_loss": 88.0,
        },
        "levels": [
            {
                "price": 95.0,
                "side": "buy",
                "quantity": 0.1,
                "status": "filled",
                "fill_price": 95.0,
            },
            {"price": 100.0, "side": "sell", "quantity": 0.1, "status": "pending"},
        ],
        "realized_pnl": 0.0,
        "is_active": True,
        "is_paused": False,
        "summary": {},
    }
    triggered = enforce_grid_stop_loss(data, 87.0, bot_id="grid-1")
    assert triggered
    assert data["is_paused"] is True
    assert data["is_active"] is False
    assert data["levels"][0]["status"] == "closed"
    assert data["levels"][1]["status"] == "cancelled"


def test_dca_stop_loss_exits_position():
    data = _dca_bot("d1", "TEST", with_position=True)
    data["config"]["stop_loss_price"] = 95.0
    data = apply_dca_tick(data, 94.0, bot_id="d1")
    assert float(data["runtime"]["position_qty"]) == 0.0
    events = data.get("recent_events") or []
    types = [e["type"] for e in events]
    assert "risk_stop_loss" in types
    stop = next(e for e in events if e["type"] == "risk_stop_loss")
    assert "Стоп усреднения" in stop["message"]
    assert "stop-loss" not in stop["message"]
