"""Grid-specific risk actions (mandatory stop-loss flatten)."""
from __future__ import annotations

from typing import Any

from app.services.bots.common import append_event


def enforce_grid_stop_loss(
    data: dict[str, Any],
    price: float,
    *,
    bot_id: str = "",
) -> bool:
    """
    When global stop-loss is breached, flatten net long exposure and halt the bot.

    Returns True if stop-loss was triggered on this tick.
    """
    cfg = data.get("config") or {}
    stop_loss = cfg.get("stop_loss")
    if stop_loss is None:
        return False
    try:
        stop = float(stop_loss)
    except (TypeError, ValueError):
        return False
    if stop <= 0 or price > stop:
        return False

    from app.services.grid.execution import record_paper_trade

    net_qty = 0.0
    cost = 0.0
    for level in list(data.get("levels") or []):
        if level.get("status") != "filled":
            continue
        qty = float(level.get("quantity") or 0.0)
        fill_price = float(level.get("fill_price") or level.get("price") or 0.0)
        if qty <= 0 or fill_price <= 0:
            continue
        if level.get("side") == "buy":
            cost += fill_price * qty
            net_qty += qty
        elif level.get("side") == "sell" and net_qty > 0:
            avg = cost / net_qty if net_qty else fill_price
            sold = min(qty, net_qty)
            cost -= avg * sold
            net_qty -= sold

    realized_delta = 0.0
    if net_qty > 0 and cost > 0:
        avg = cost / net_qty
        pnl = (price - avg) * net_qty
        realized_delta = pnl
        if bot_id:
            record_paper_trade(
                data,
                bot_id=bot_id,
                side="sell",
                price=price,
                quantity=net_qty,
                level_price=avg,
                pnl=pnl,
            )
        data["realized_pnl"] = round(float(data.get("realized_pnl", 0.0)) + pnl, 4)

    for level in data.get("levels") or []:
        if level.get("status") == "pending":
            level["status"] = "cancelled"
        elif level.get("status") == "filled" and level.get("side") == "buy":
            level["status"] = "closed"
            level["barrier_status"] = "sl"

    data["is_active"] = False
    data["is_paused"] = True
    data["risk_halt"] = True
    data["barrier_positions"] = []
    data["dca_state"] = {"active": False, "direction": "buy", "entries": [], "avg_entry": 0.0, "total_qty": 0.0}

    summary = data.get("summary") or {}
    summary["is_active"] = False
    summary["unrealized_pnl"] = 0.0
    summary["total_pnl"] = round(float(data.get("realized_pnl", 0.0)), 4)
    summary["last_price"] = price
    data["summary"] = summary
    data["unrealized_pnl"] = 0.0
    data["total_pnl"] = summary["total_pnl"]

    append_event(
        data,
        "risk_stop_loss",
        f"Grid stop-loss @ ${price:.2f} (limit ${stop:.2f}) — positions flattened",
        price=price,
        pnl_delta=round(realized_delta, 4) if realized_delta else None,
        side="sell",
    )
    return True
