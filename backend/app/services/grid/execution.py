"""Grid bot paper trade recording and open-position aggregation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TRADES = 100


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_paper_trade(
    data: dict[str, Any],
    *,
    bot_id: str,
    side: str,
    price: float,
    quantity: float,
    level_price: float,
    pnl: float,
) -> dict[str, Any]:
    """Append a paper fill to the bot's trade log (persisted in Redis with bot state)."""
    from app.services.pretrade.policy import evaluate

    bot_user = str(data.get("user_id") or data.get("email") or bot_id)
    cfg = data.get("config") if isinstance(data.get("config"), dict) else {}
    # GA16-316: never invent UNKNOWN ticker or USD currency.
    raw_ticker = data.get("symbol") or data.get("ticker") or cfg.get("ticker")
    bot_ticker = str(raw_ticker).strip() if raw_ticker not in (None, "") else ""
    if not bot_ticker:
        logger.warning("Grid paper trade blocked: missing ticker", bot_id=bot_id)
        return {
            "blocked": True,
            "error": "Не указан инструмент сетки.",
            "trades_recorded": 0,
        }
    raw_nav = data.get("nav") or cfg.get("total_capital")
    nav = float(raw_nav) if raw_nav not in (None, "") else None
    try:
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
            logger.info("Grid paper trade blocked by pretrade", bot_id=bot_id, ticker=bot_ticker)
            return {"blocked": True, "risk": decision.as_dict(), "trades_recorded": 0}
    except Exception as exc:
        logger.warning("Grid pretrade failed; trade not recorded", bot_id=bot_id, error=str(exc))
        return {
            "blocked": True,
            "error": "Проверка риска недоступна. Сделка не записана.",
            "trades_recorded": 0,
        }
    trades: list[dict[str, Any]] = list(data.get("paper_trades") or [])
    trade = {
        "id": str(uuid4()),
        "bot_id": bot_id,
        "ts": _utc_now_iso(),
        "side": side,
        "price": round(price, 6),
        "quantity": round(quantity, 6),
        "level_price": round(level_price, 6),
        "notional_usd": round(price * quantity, 4),
        "pnl": round(pnl, 4),
    }
    trades.append(trade)
    data["paper_trades"] = trades[-_MAX_TRADES:]
    raw_ccy = data.get("ccy") or cfg.get("ccy") or cfg.get("currency")
    ccy = str(raw_ccy).strip() if raw_ccy not in (None, "") else ""
    if ccy:
        try:
            from app.services.portfolio_book.service import record_bot_trade

            record_bot_trade(
                user_id=str(data.get("user_id") or data.get("email") or bot_id),
                ticker=bot_ticker,
                qty=quantity,
                amount=trade["notional_usd"],
                ccy=ccy,
                side=side,
                external_id=f"grid:{trade['id']}",
                event_time=datetime.now(timezone.utc),
            )
        except Exception:
            logger.debug("portfolio_book grid trade skipped", bot_id=bot_id)
    else:
        logger.debug("portfolio_book grid trade skipped: no currency", bot_id=bot_id)
    logger.info(
        "Grid paper trade recorded",
        bot_id=bot_id,
        side=side,
        price=price,
        qty=quantity,
        pnl=pnl,
    )
    return trade


def compute_open_positions(data: dict[str, Any], current_price: float | None) -> list[dict[str, Any]]:
    """
    Net long exposure from filled grid levels.
    Each filled buy adds quantity; each filled sell reduces it (FIFO-style net).
    """
    cfg = data.get("config", {})
    ticker = cfg.get("ticker", "")
    bot_id = data.get("bot_id", "")

    net_qty = 0.0
    cost_basis = 0.0

    for level in data.get("levels", []):
        if level.get("status") != "filled":
            continue
        qty = float(level.get("quantity") or 0)
        fill_price = level.get("fill_price") or level.get("price")
        if not fill_price or qty <= 0:
            continue
        fill_price = float(fill_price)
        if level.get("side") == "buy":
            cost_basis += fill_price * qty
            net_qty += qty
        elif level.get("side") == "sell":
            if net_qty > 0:
                avg = cost_basis / net_qty if net_qty else fill_price
                cost_basis -= avg * min(qty, net_qty)
                net_qty -= qty

    if net_qty <= 1e-9:
        return []

    avg_entry = cost_basis / net_qty if net_qty else 0.0
    mark = float(current_price or data.get("summary", {}).get("last_price") or avg_entry)
    unrealized = (mark - avg_entry) * net_qty

    return [{
        "bot_id": bot_id,
        "ticker": ticker,
        "side": "long",
        "quantity": round(net_qty, 6),
        "avg_entry": round(avg_entry, 4),
        "mark_price": round(mark, 4),
        "notional_usd": round(net_qty * mark, 2),
        "unrealized_pnl": round(unrealized, 4),
    }]
