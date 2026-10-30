"""Standalone momentum bot — directional entries from price momentum."""
from __future__ import annotations

from typing import Any

from app.services.bot_risk.guard import get_bot_risk_guard
from app.services.bot_risk.types import PortfolioSnapshot
from app.services.bots.common import (
    append_event,
    append_pnl_snapshot,
    record_paper_trade,
    recompute_pnl,
)


def new_runtime(entry_price: float) -> dict[str, Any]:
    return {
        "executor_state": "watching",
        "position_qty": 0.0,
        "avg_entry": 0.0,
        "price_history": [round(entry_price, 6)],
        "last_price": entry_price,
        "last_momentum": 0.0,
    }


def _momentum(prices: list[float], lookback: int) -> float:
    if len(prices) <= lookback or lookback <= 0:
        return 0.0
    base = prices[-lookback - 1]
    if base <= 0:
        return 0.0
    return (prices[-1] / base) - 1.0


def apply_momentum_tick(
    data: dict[str, Any],
    price: float,
    *,
    bot_id: str,
    risk_snapshot: PortfolioSnapshot | None = None,
) -> dict[str, Any]:
    if price <= 0:
        return data

    cfg = data["config"]
    runtime = data.setdefault("runtime", new_runtime(float(cfg.get("entry_price", price))))
    runtime["last_price"] = round(price, 6)

    history: list[float] = list(runtime.get("price_history") or [])
    history.append(round(price, 6))
    max_hist = max(int(cfg.get("lookback_ticks", 20)) * 3, 60)
    runtime["price_history"] = history[-max_hist:]

    if data.get("is_paused") or not data.get("is_active", True):
        recompute_pnl(data, price)
        return data

    lookback = int(cfg.get("lookback_ticks", 20))
    entry_threshold = float(cfg.get("entry_momentum_pct", 0.03))
    take_profit_pct = float(cfg.get("take_profit_pct", 0.06))
    stop_loss_pct = float(cfg.get("stop_loss_pct", 0.04))
    position_pct = float(cfg.get("position_size_pct", 0.5))
    total_capital = float(cfg.get("total_capital", 10_000.0))

    mom = _momentum(history, lookback)
    runtime["last_momentum"] = round(mom, 6)

    qty = float(runtime.get("position_qty", 0.0) or 0.0)
    avg = float(runtime.get("avg_entry", 0.0) or 0.0)

    def _exit(reason: str, pnl: float) -> None:
        nonlocal qty, avg
        record_paper_trade(data, bot_id=bot_id, side="sell", price=price, quantity=qty, pnl=pnl)
        data["realized_pnl"] = round(float(data.get("realized_pnl", 0.0)) + pnl, 4)
        append_event(data, "exit", reason, price=price, pnl_delta=pnl, side="sell")
        runtime.update({
            "position_qty": 0.0,
            "avg_entry": 0.0,
            "executor_state": "watching",
        })
        qty = 0.0
        avg = 0.0

    if qty > 0 and avg > 0:
        if price <= avg * (1.0 - stop_loss_pct):
            _exit(f"Momentum stop-loss @ {price:.2f}", (price - avg) * qty)
        elif price >= avg * (1.0 + take_profit_pct):
            _exit(f"Momentum take-profit @ {price:.2f}", (price - avg) * qty)
        elif mom < 0:
            _exit(f"Momentum reversal (mom={mom:.2%})", (price - avg) * qty)

    qty = float(runtime.get("position_qty", 0.0) or 0.0)
    if qty <= 0 and mom >= entry_threshold and len(history) > lookback:
        guard = get_bot_risk_guard()
        stop_price = price * (1.0 - stop_loss_pct)
        notional = total_capital * position_pct
        if risk_snapshot is not None:
            gate = guard.gate_new_position(
                ticker=str(cfg.get("ticker", "")),
                portfolio_usd=total_capital,
                entry_price=price,
                stop_loss_price=stop_price,
                snapshot=risk_snapshot,
                bot_id=bot_id,
            )
            if not gate.allowed:
                append_event(data, "risk_block", gate.reason, price=price)
                recompute_pnl(data, price)
                append_pnl_snapshot(data, float(data.get("total_pnl", 0.0)))
                return data
            if gate.correlation and gate.correlation.conflicting_bots:
                append_event(data, "risk_warn", gate.correlation.reason, price=price)
            if gate.sizing and gate.sizing.allowed:
                notional = min(notional, gate.sizing.notional_usd)
        else:
            sized = guard.compute_position_size(
                portfolio_usd=total_capital,
                entry_price=price,
                stop_loss_price=stop_price,
            )
            if sized.allowed:
                notional = min(notional, sized.notional_usd)
        buy_qty = notional / price
        record_paper_trade(data, bot_id=bot_id, side="buy", price=price, quantity=buy_qty)
        append_event(
            data,
            "momentum_entry",
            f"Momentum entry mom={mom:.2%} @ {price:.2f}",
            price=price,
            side="buy",
        )
        runtime.update({
            "position_qty": round(buy_qty, 8),
            "avg_entry": round(price, 6),
            "executor_state": "in_position",
        })

    recompute_pnl(data, price)
    append_pnl_snapshot(data, float(data.get("total_pnl", 0.0)))
    return data
