"""Activity log helpers shared by DCA and momentum bots."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_EVENTS = 20
_MAX_PNL_SNAPSHOTS = 60
_MAX_TRADES = 100


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_event(
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
        "ts": utc_now_iso(),
        "type": event_type,
        "message": message,
        "price": price,
        "pnl_delta": pnl_delta,
        "side": side,
    })
    data["recent_events"] = events[-_MAX_EVENTS:]
    data["last_activity_at"] = events[-1]["ts"]


def append_pnl_snapshot(data: dict[str, Any], total_pnl: float) -> None:
    snapshots: list[dict[str, Any]] = list(data.get("pnl_snapshots") or [])
    snapshots.append({"ts": utc_now_iso(), "total_pnl": round(total_pnl, 4)})
    data["pnl_snapshots"] = snapshots[-_MAX_PNL_SNAPSHOTS:]


def init_activity_state(data: dict[str, Any], *, message: str) -> None:
    now = utc_now_iso()
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
    total = float(data.get("total_pnl", 0.0) or 0.0)
    start = float(data.get("session_start_pnl", 0.0) or 0.0)
    return round(total - start, 4)


def record_paper_trade(
    data: dict[str, Any],
    *,
    bot_id: str,
    side: str,
    price: float,
    quantity: float,
    pnl: float = 0.0,
) -> dict[str, Any]:
    try:
        from app.services.pretrade.policy import evaluate

        bot_user = str(data.get("user_id") or data.get("email") or bot_id)
        bot_ticker = str(data.get("symbol") or data.get("ticker") or "UNKNOWN")
        cfg = data.get("config") if isinstance(data.get("config"), dict) else {}
        raw_nav = data.get("nav") or cfg.get("total_capital")
        nav = float(raw_nav) if raw_nav not in (None, "") else None
        decision = evaluate(
            kind="bot",
            actor="auto",
            user_id=bot_user,
            ticker=bot_ticker,
            qty=float(quantity),
            price=float(price),
            mode="paper",
            nav=nav,
        )
        if decision.verdict == "block":
            append_event(data, "risk_block", decision.reasons[0].detail if decision.reasons else "risk_gate")
            return {"blocked": True, "risk": decision.as_dict(), "trades_recorded": 0}
    except Exception as exc:
        append_event(data, "risk_block", f"риск-гейт недоступен: {exc}")
        return {"blocked": True, "error": str(exc), "trades_recorded": 0}
    trades: list[dict[str, Any]] = list(data.get("paper_trades") or [])
    trade = {
        "id": str(uuid4()),
        "bot_id": bot_id,
        "ts": utc_now_iso(),
        "side": side,
        "price": round(price, 6),
        "quantity": round(quantity, 6),
        "notional_usd": round(price * quantity, 4),
        "pnl": round(pnl, 4),
    }
    trades.append(trade)
    data["paper_trades"] = trades[-_MAX_TRADES:]
    data["total_trades"] = int(data.get("total_trades", 0) or 0) + 1
    try:
        from datetime import datetime, timezone

        from app.services.portfolio_book.service import record_bot_trade

        record_bot_trade(
            user_id=str(data.get("user_id") or data.get("email") or bot_id),
            ticker=str(data.get("symbol") or data.get("ticker") or "UNKNOWN"),
            qty=quantity,
            amount=trade["notional_usd"],
            ccy="USD",
            side=side,
            external_id=f"bots:{trade['id']}",
            event_time=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.warning("portfolio_book bot trade skipped", bot_id=bot_id, error=str(exc)[:200])
    return trade


def recompute_pnl(data: dict[str, Any], last_price: float | None) -> None:
    runtime = data.setdefault("runtime", {})
    qty = float(runtime.get("position_qty", 0.0) or 0.0)
    avg = float(runtime.get("avg_entry", 0.0) or 0.0)
    realized = float(data.get("realized_pnl", 0.0) or 0.0)
    unrealized = 0.0
    if qty > 0 and last_price and avg > 0:
        unrealized = (last_price - avg) * qty
    data["unrealized_pnl"] = round(unrealized, 4)
    data["total_pnl"] = round(realized + unrealized, 4)
    if last_price is not None:
        runtime["last_price"] = round(last_price, 6)


def build_summary(bot_id: str, data: dict[str, Any]) -> dict[str, Any]:
    cfg = data.get("config", {})
    runtime = data.get("runtime", {})
    last_price = runtime.get("last_price")
    recompute_pnl(data, float(last_price) if last_price is not None else None)
    return {
        "bot_id": bot_id,
        "ticker": cfg.get("ticker", ""),
        "total_capital": cfg.get("total_capital", 0.0),
        "is_active": data.get("is_active", True),
        "is_paused": data.get("is_paused", False),
        "total_trades": data.get("total_trades", 0),
        "realized_pnl": data.get("realized_pnl", 0.0),
        "unrealized_pnl": data.get("unrealized_pnl", 0.0),
        "total_pnl": data.get("total_pnl", 0.0),
        "last_price": last_price,
        "last_activity_at": data.get("last_activity_at"),
        "session_pnl": session_pnl(data),
        "executor_state": runtime.get("executor_state", "idle"),
        "entries_count": runtime.get("entries_count", 0),
        "position_qty": runtime.get("position_qty", 0.0),
    }
