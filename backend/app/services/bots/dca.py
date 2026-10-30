"""Standalone DCA bot — scheduled/dip averaging, not grid band escape."""
from __future__ import annotations

from typing import Any

from app.services.bot_risk.guard import get_bot_risk_guard
from app.services.bot_risk.position_sizing import default_stop_loss_price
from app.services.bot_risk.types import PortfolioSnapshot
from app.services.bots.common import (
    append_event,
    append_pnl_snapshot,
    record_paper_trade,
    recompute_pnl,
)


def new_runtime(entry_price: float) -> dict[str, Any]:
    return {
        "executor_state": "accumulating",
        "position_qty": 0.0,
        "avg_entry": 0.0,
        "entries_count": 0,
        "ticks_since_last_buy": 0,
        "last_buy_price": entry_price,
        "last_price": entry_price,
        "deployed_usd": 0.0,
    }


def apply_dca_tick(
    data: dict[str, Any],
    price: float,
    *,
    bot_id: str,
    risk_snapshot: PortfolioSnapshot | None = None,
) -> dict[str, Any]:
    """Paper DCA: buy on interval or dip; exit on take-profit or stop-loss."""
    if price <= 0:
        return data

    cfg = data["config"]
    runtime = data.setdefault("runtime", new_runtime(float(cfg.get("entry_price", price))))
    runtime["last_price"] = round(price, 6)

    if data.get("is_paused") or not data.get("is_active", True):
        recompute_pnl(data, price)
        return data

    guard = get_bot_risk_guard()
    stop_loss_pct = float(cfg.get("stop_loss_pct", guard.config.default_stop_loss_pct))
    if cfg.get("stop_loss_price") is None and price > 0:
        cfg["stop_loss_price"] = default_stop_loss_price(
            entry_price=price,
            stop_loss_pct=stop_loss_pct,
        )

    raw_size = cfg.get("order_size_usd")
    order_usd = float(raw_size) if raw_size not in (None, "") else 0.0
    if order_usd < 0:
        order_usd = 0.0
    max_entries = int(cfg.get("max_entries", 10))
    interval_ticks = int(cfg.get("interval_ticks", 5))
    dip_pct = float(cfg.get("dip_pct", 0.02))
    take_profit_pct = float(cfg.get("take_profit_pct", 0.05))
    raw_capital = cfg.get("total_capital")
    total_capital = float(raw_capital) if raw_capital not in (None, "") else order_usd * max_entries

    qty = float(runtime.get("position_qty", 0.0) or 0.0)
    avg = float(runtime.get("avg_entry", 0.0) or 0.0)
    entries = int(runtime.get("entries_count", 0) or 0)
    deployed = float(runtime.get("deployed_usd", 0.0) or 0.0)
    ticks = int(runtime.get("ticks_since_last_buy", 0) or 0) + 1
    runtime["ticks_since_last_buy"] = ticks

    stop_price = float(cfg.get("stop_loss_price") or 0.0)
    if qty > 0 and avg > 0 and stop_price > 0 and price <= stop_price:
        pnl = (price - avg) * qty
        record_paper_trade(data, bot_id=bot_id, side="sell", price=price, quantity=qty, pnl=pnl)
        data["realized_pnl"] = round(float(data.get("realized_pnl", 0.0)) + pnl, 4)
        append_event(
            data,
            "risk_stop_loss",
            f"Стоп усреднения по {price:.2f} (порог {stop_price:.2f})",
            price=price,
            pnl_delta=pnl,
            side="sell",
        )
        runtime.update({
            "position_qty": 0.0,
            "avg_entry": 0.0,
            "entries_count": 0,
            "deployed_usd": 0.0,
            "executor_state": "flat",
            "ticks_since_last_buy": 0,
            "last_buy_price": price,
        })
        recompute_pnl(data, price)
        append_pnl_snapshot(data, float(data.get("total_pnl", 0.0)))
        return data

    if qty > 0 and avg > 0 and price >= avg * (1.0 + take_profit_pct):
        pnl = (price - avg) * qty
        record_paper_trade(data, bot_id=bot_id, side="sell", price=price, quantity=qty, pnl=pnl)
        data["realized_pnl"] = round(float(data.get("realized_pnl", 0.0)) + pnl, 4)
        append_event(
            data,
            "take_profit",
            f"DCA take-profit @ {price:.2f} (+{take_profit_pct*100:.1f}%)",
            price=price,
            pnl_delta=pnl,
            side="sell",
        )
        runtime.update({
            "position_qty": 0.0,
            "avg_entry": 0.0,
            "entries_count": 0,
            "deployed_usd": 0.0,
            "executor_state": "flat",
            "ticks_since_last_buy": 0,
            "last_buy_price": price,
        })
        recompute_pnl(data, price)
        append_pnl_snapshot(data, float(data.get("total_pnl", 0.0)))
        return data

    last_buy = float(runtime.get("last_buy_price", price) or price)
    dip_trigger = last_buy > 0 and price <= last_buy * (1.0 - dip_pct)
    interval_trigger = ticks >= interval_ticks and entries < max_entries

    if qty == 0 and entries == 0:
        interval_trigger = True

    can_buy = (
        order_usd > 0
        and entries < max_entries
        and deployed + order_usd <= total_capital + 1e-6
        and (interval_trigger or dip_trigger)
    )

    if can_buy:
        total_capital = float(cfg.get("total_capital", order_usd * max_entries))
        stop_for_size = float(cfg.get("stop_loss_price") or default_stop_loss_price(
            entry_price=price,
            stop_loss_pct=stop_loss_pct,
        ))
        if risk_snapshot is not None:
            gate = guard.gate_new_position(
                ticker=str(cfg.get("ticker", "")),
                portfolio_usd=total_capital,
                entry_price=price,
                stop_loss_price=stop_for_size,
                snapshot=risk_snapshot,
                bot_id=bot_id,
            )
            if not gate.allowed:
                append_event(data, "risk_block", gate.reason, price=price)
                recompute_pnl(data, price)
                return data
            if gate.correlation and gate.correlation.conflicting_bots:
                append_event(data, "risk_warn", gate.correlation.reason, price=price)
            if gate.sizing and gate.sizing.allowed:
                order_usd = min(order_usd, gate.sizing.notional_usd)
        else:
            sized = guard.compute_position_size(
                portfolio_usd=total_capital,
                entry_price=price,
                stop_loss_price=stop_for_size,
            )
            if sized.allowed:
                order_usd = min(order_usd, sized.notional_usd)

        buy_qty = order_usd / price
        notional_before = avg * qty
        qty += buy_qty
        avg = (notional_before + order_usd) / qty if qty else price
        entries += 1
        deployed += order_usd
        record_paper_trade(data, bot_id=bot_id, side="buy", price=price, quantity=buy_qty)
        append_event(
            data,
            "dca_buy",
            f"DCA buy #{entries}: ${order_usd:.0f} @ {price:.2f}"
            + (" (dip)" if dip_trigger and not interval_trigger else ""),
            price=price,
            side="buy",
        )
        runtime.update({
            "position_qty": round(qty, 8),
            "avg_entry": round(avg, 6),
            "entries_count": entries,
            "deployed_usd": round(deployed, 4),
            "executor_state": "accumulating" if entries < max_entries else "full",
            "ticks_since_last_buy": 0,
            "last_buy_price": price,
        })

    recompute_pnl(data, price)
    append_pnl_snapshot(data, float(data.get("total_pnl", 0.0)))
    return data
