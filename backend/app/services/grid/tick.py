"""Grid bot price tick — shared fill simulation for API and Celery."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.services.bot_risk.types import PortfolioSnapshot
from app.services.grid.config import GridConfigModel
from app.services.grid.engine import GridBotEngine, GridConfig, GridLevel
from app.services.grid.executor import GridExecutor

logger = get_logger(__name__)

_MAX_EVENTS = 20
_MAX_PNL_SNAPSHOTS = 60


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_event(
    data: dict[str, Any],
    event_type: str,
    message: str,
    *,
    price: float | None = None,
    pnl_delta: float | None = None,
    side: str | None = None,
) -> None:
    events: list[dict[str, Any]] = list(data.get("recent_events") or [])
    events.append({
        "ts": _utc_now_iso(),
        "type": event_type,
        "message": message,
        "price": price,
        "pnl_delta": pnl_delta,
        "side": side,
    })
    data["recent_events"] = events[-_MAX_EVENTS:]
    data["last_activity_at"] = events[-1]["ts"]


def _append_pnl_snapshot(data: dict[str, Any], total_pnl: float) -> None:
    snapshots: list[dict[str, Any]] = list(data.get("pnl_snapshots") or [])
    snapshots.append({"ts": _utc_now_iso(), "total_pnl": round(total_pnl, 4)})
    data["pnl_snapshots"] = snapshots[-_MAX_PNL_SNAPSHOTS:]


def init_activity_state(data: dict[str, Any], *, message: str = "Bot created") -> None:
    """Seed activity fields for a newly created bot."""
    now = _utc_now_iso()
    data["last_activity_at"] = now
    data["session_start_pnl"] = 0.0
    data["recent_events"] = [{
        "ts": now,
        "type": "created",
        "message": message,
        "price": data.get("config", {}).get("entry_price"),
        "pnl_delta": None,
        "side": None,
    }]
    data["pnl_snapshots"] = [{"ts": now, "total_pnl": 0.0}]


def session_pnl(data: dict[str, Any]) -> float:
    summary = data.get("summary") or {}
    total = float(summary.get("total_pnl", 0.0) or 0.0)
    start = float(data.get("session_start_pnl", 0.0) or 0.0)
    return round(total - start, 4)


def build_activity_payload(bot_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build activity response dict from stored bot state."""
    from app.services.grid.execution import compute_open_positions

    data = recompute_summary(data)
    data["bot_id"] = bot_id
    cfg = data.get("config", {})
    summary = data.get("summary", {})
    levels = data.get("levels", [])

    pending = [l for l in levels if l.get("status") == "pending"]
    recent_fills = [l for l in levels if l.get("status") == "filled"][-10:]

    last_price = summary.get("last_price")
    open_positions = compute_open_positions(data, last_price)
    paper_trades = list(data.get("paper_trades") or [])[-20:]

    barrier_map = {
        bp["level_id"]: bp
        for bp in (data.get("barrier_positions") or [])
    }

    all_levels = sorted(
        [
            {
                "price": l.get("price"),
                "side": l.get("side"),
                "status": l.get("status"),
                "quantity": l.get("quantity"),
                "fill_price": l.get("fill_price"),
                "pnl": l.get("pnl", 0.0),
                "barrier_id": l.get("barrier_id"),
                "barrier_status": _barrier_status_for_level(l, barrier_map),
            }
            for l in levels
        ],
        key=lambda x: float(x["price"] or 0),
    )

    return {
        "bot_id": bot_id,
        "ticker": cfg.get("ticker", summary.get("ticker", "")),
        "last_price": last_price,
        "last_activity_at": data.get("last_activity_at"),
        "session_pnl": session_pnl(data),
        "total_pnl": summary.get("total_pnl", 0.0),
        "realized_pnl": data.get("realized_pnl", 0.0),
        "unrealized_pnl": summary.get("unrealized_pnl", 0.0),
        "pending_levels": pending,
        "recent_fills": recent_fills,
        "grid_levels": all_levels,
        "recent_events": list(data.get("recent_events") or [])[-10:],
        "pnl_snapshots": list(data.get("pnl_snapshots") or [])[-30:],
        "paper_trades": paper_trades,
        "open_positions": open_positions,
        "pending_orders": summary.get("pending_orders", len(pending)),
        "filled_orders": summary.get("filled_orders", len(recent_fills)),
        "lower_price": cfg.get("lower_price"),
        "upper_price": cfg.get("upper_price"),
        "grid_count": cfg.get("grid_count"),
        "grid_type": cfg.get("grid_type", "geometric"),
        "is_active": data.get("is_active", True),
        "is_paused": data.get("is_paused", False),
        "total_trades": data.get("total_trades", 0),
        "total_capital": cfg.get("total_capital"),
        "executor_state": data.get("executor_state", "grid_active"),
        "circuit_breaker": data.get("circuit_breaker"),
        "dca_state": data.get("dca_state"),
        "barrier_positions": data.get("barrier_positions") or [],
        "trailing_enabled": cfg.get("trailing_enabled", False),
    }


def _barrier_status_for_level(level: dict, barrier_map: dict) -> str:
    bid = level.get("barrier_id")
    if not bid:
        return "none" if level.get("status") != "filled" else "active"
    bp = barrier_map.get(bid)
    if not bp:
        return "active"
    if bp.get("is_closed"):
        return bp.get("exit_reason", "closed")
    return "active"


def _restore_bot(data: dict[str, Any]) -> tuple[GridBotEngine, float]:
    cfg_data = data["config"]
    cfg = GridConfig(
        ticker=cfg_data["ticker"],
        lower_price=cfg_data["lower_price"],
        upper_price=cfg_data["upper_price"],
        grid_count=cfg_data["grid_count"],
        total_capital=cfg_data["total_capital"],
        take_profit=cfg_data.get("take_profit"),
        stop_loss=cfg_data.get("stop_loss"),
        grid_type=cfg_data.get("grid_type", "geometric"),
        trailing_enabled=bool(cfg_data.get("trailing_enabled", False)),
        trailing_offset_pct=float(cfg_data.get("trailing_offset_pct", 0.02)),
    )
    bot = GridBotEngine(cfg)
    bot.state.realized_pnl = data.get("realized_pnl", 0.0)
    bot.state.total_trades = data.get("total_trades", 0)
    bot.state.is_active = data.get("is_active", True)

    prev_price = data.get("summary", {}).get("last_price") or cfg_data.get("entry_price", 0.0)
    for l_data in data.get("levels", []):
        level = GridLevel(
            price=l_data["price"],
            side=l_data["side"],
            quantity=l_data["quantity"],
        )
        level.status = l_data.get("status", "pending")
        level.fill_price = l_data.get("fill_price")
        level.pnl = l_data.get("pnl", 0.0)
        level.barrier_id = l_data.get("barrier_id")
        level.barrier_status = l_data.get("barrier_status", "active")
        bot.state.levels.append(level)
    return bot, float(prev_price or 0.0)


def _sync_levels_from_executor(data: dict[str, Any], executor: GridExecutor) -> None:
    bot = executor.engine
    data["levels"] = [
        {
            "price": l.price,
            "side": l.side,
            "quantity": l.quantity,
            "status": l.status,
            "fill_price": l.fill_price,
            "pnl": l.pnl,
            "barrier_id": getattr(l, "barrier_id", None),
            "barrier_status": getattr(l, "barrier_status", "active"),
        }
        for l in bot.state.levels
    ]
    data["realized_pnl"] = bot.state.realized_pnl
    data["total_trades"] = bot.state.total_trades
    data["is_active"] = bot.state.is_active
    summary = bot.get_summary()
    summary["last_price"] = bot.state.last_price
    data["summary"] = summary
    executor.persist_to_dict(data)


def apply_price_tick(
    data: dict[str, Any],
    price: float,
    *,
    bot_id: str | None = None,
    risk_snapshot: PortfolioSnapshot | None = None,
) -> dict[str, Any]:
    """Simulate grid fills for a price update. Returns mutated bot state dict."""
    from app.services.bot_risk.grid_actions import enforce_grid_stop_loss
    from app.services.grid.execution import record_paper_trade

    if not data.get("is_active", True):
        return data

    resolved_bot_id = bot_id or data.get("bot_id", "")

    # Mandatory global stop-loss — flatten before any new fills
    if enforce_grid_stop_loss(data, price, bot_id=resolved_bot_id):
        _append_pnl_snapshot(data, float(data.get("total_pnl", 0.0)))
        return data

    if data.get("is_paused"):
        bot, _ = _restore_bot(data)
        summary = bot.get_summary()
        summary["last_price"] = price
        data["summary"] = summary
        _append_event(
            data,
            "tick",
            f"Price tick ${price:.2f} (paused — no fills)",
            price=price,
        )
        return data

    executor = GridExecutor.from_bot_data(data)
    prev_price = float(
        data.get("summary", {}).get("last_price")
        or data.get("config", {}).get("entry_price", 0.0)
        or price
    )
    if prev_price <= 0:
        prev_price = price

    pnl_before = executor.engine.state.realized_pnl + executor.engine.state.unrealized_pnl
    fills_before = executor.engine.state.total_trades

    result = executor.on_price_tick(price, prev_price)
    executor.engine.state.last_price = price
    _sync_levels_from_executor(data, executor)

    # Circuit breaker events
    if result.circuit_event:
        ev = result.circuit_event
        _append_event(
            data,
            "circuit_breaker",
            f"Circuit breaker {ev['event']}: {ev['reason']}",
            price=price,
        )

    # State transitions
    if result.state_changed:
        _append_event(
            data,
            "state_change",
            f"Executor → {result.new_state.value}",
            price=price,
        )

    if result.trailing_shifted:
        _append_event(data, "trailing", "Trailing grid range shifted upward", price=price)

    if result.dca_action:
        _append_event(data, "dca", result.dca_action, price=price)

    for close in result.barrier_closes:
        _append_event(
            data,
            "barrier_exit",
            f"Triple-barrier {close['exit_reason']} @ ${close['exit_price']:.2f}",
            price=close["exit_price"],
            pnl_delta=round(close.get("pnl", 0.0), 4),
        )

    pnl_after = executor.engine.state.realized_pnl + executor.engine.state.unrealized_pnl
    price_moved = abs(price - prev_price) > 1e-9
    _append_event(
        data,
        "tick",
        f"Price tick ${price:.2f}" + ("" if price_moved else " (unchanged)"),
        price=price,
        pnl_delta=round(pnl_after - pnl_before, 4) if pnl_after != pnl_before else None,
    )

    for level in result.filled_levels:
        _append_event(
            data,
            "fill",
            f"{level.side.upper()} filled @ ${level.price:.2f}",
            price=level.price,
            pnl_delta=round(level.pnl, 4) if level.pnl else None,
            side=level.side,
        )
        if resolved_bot_id:
            record_paper_trade(
                data,
                bot_id=resolved_bot_id,
                side=level.side,
                price=float(level.price),
                quantity=float(level.quantity),
                level_price=float(level.price),
                pnl=float(level.pnl or 0.0),
            )

    _append_pnl_snapshot(data, pnl_after)

    if executor.engine.state.total_trades > fills_before:
        logger.info(
            "Grid bot fills",
            ticker=data["config"]["ticker"],
            fills=executor.engine.state.total_trades - fills_before,
            price=price,
        )
    return data


def recompute_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Refresh summary counters from stored levels without a price tick."""
    bot, last_price = _restore_bot(data)
    price = last_price or data.get("summary", {}).get("last_price") or 0.0
    if price > 0:
        bot.update_unrealized_pnl(price)
    data["summary"] = bot.get_summary()
    return data
