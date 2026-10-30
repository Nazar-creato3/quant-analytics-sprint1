"""Manual order placement service (spec B.1–B.4)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import ManualOrder, Maneuver
from app.schemas.orders import (
    ManualOrderCreate,
    ManualOrderOut,
    OrderBookSnapshot,
    OrderTicketPrefill,
    SlippageEstimate,
)
from app.services.execution.adapter import OrderRequest
from app.services.execution.guard import ManualOrderExecutionContext
from app.services.orders.order_book import fetch_order_book
from app.services.orders.recent_trades import fetch_recent_trades
from app.services.orders.slippage import estimate_slippage
from app.utils.audit import AuditAction, audit

logger = get_logger(__name__)

CONDITIONAL_TYPES = frozenset({"oco", "trailing_stop", "stop", "stop_limit"})
LIVE_BROKER_STOP_TYPES = frozenset({"stop", "stop_limit"})


def _expiry_at_from_meta(maneuver: Maneuver) -> datetime | None:
    meta = getattr(maneuver, "signal_meta", None) or {}
    if not isinstance(meta, dict):
        return None
    raw = meta.get("expiry_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _apply_position_expiry(
    maneuver: Maneuver,
    *,
    time_horizon: str | None,
    expiry_at: datetime | None,
) -> dict[str, str]:
    from app.services.portfolio.position_analytics import apply_horizon_expiry_overrides

    return apply_horizon_expiry_overrides(
        maneuver,
        time_horizon=time_horizon,
        expiry_at=expiry_at,
    )


def _fees_usd(notional: float) -> float:
    return round(notional * settings.COMMISSION_RATE_PCT / 100.0, 4)


async def build_prefill_from_maneuver(
    db: AsyncSession,
    maneuver_id: str,
    *,
    portfolio_size: float,
    user_id: str | None = None,
) -> OrderTicketPrefill:
    from app.services.portfolio.user_scope import load_maneuver_for_user

    if user_id:
        maneuver = await load_maneuver_for_user(db, user_id, maneuver_id)
    else:
        result = await db.execute(select(Maneuver).where(Maneuver.id == maneuver_id))
        maneuver = result.scalar_one_or_none()
    if not maneuver:
        raise ValueError("Maneuver not found")
    from app.services.instrument.data_only import assert_execution_allowed

    assert_execution_allowed(maneuver.ticker)
    if maneuver.direction == "neutral":
        raise ValueError("Cannot prefill from NO_TRADE maneuver")

    entry = maneuver.entry_zone_high or maneuver.entry_zone_low or maneuver.fill_price
    if not entry or entry <= 0:
        raise ValueError("Maneuver has no entry price")

    qty = maneuver.position_size_usd / entry if entry > 0 else 0
    side = "buy" if maneuver.direction == "long" else "sell"
    position_pct = (
        maneuver.position_size_usd / portfolio_size * 100 if portfolio_size > 0 else 0
    )

    from app.schemas.orders import BracketLeg

    bracket = None
    if maneuver.stop_loss or maneuver.take_profit:
        bracket = BracketLeg(
            stop_loss=maneuver.stop_loss,
            take_profit=maneuver.take_profit,
        )

    return OrderTicketPrefill(
        ticker=maneuver.ticker,
        side=side,
        quantity=round(qty, 6),
        limit_price=round(entry, 4),
        stop_price=maneuver.stop_loss,
        take_profit=maneuver.take_profit,
        stop_loss=maneuver.stop_loss,
        position_size_usd=maneuver.position_size_usd,
        position_pct=round(position_pct, 4),
        maneuver_id=maneuver.id,
        direction=maneuver.direction,
        time_horizon=maneuver.time_horizon,
        expiry_at=_expiry_at_from_meta(maneuver),
        bracket=bracket,
    )


async def submit_manual_order(
    db: AsyncSession,
    body: ManualOrderCreate,
    *,
    user_id: str | None,
    user_email: str,
) -> ManualOrderOut:
    """Place a manual order — user submits explicitly; no auto-execution from maneuvers."""
    from app.services.instrument.data_only import assert_execution_allowed
    from app.services.orders.symbol_rules import get_symbol_trading_rules, validate_order_qty_price

    assert_execution_allowed(body.ticker)

    mode = body.trading_mode or "paper"
    if mode == "live":
        if not user_id:
            raise ValueError("Для сделки на реальном счёте нужно войти в аккаунт")
        from app.services.trading_keys.user_executor import live_unavailable_reason

        reason = await live_unavailable_reason(db, user_id)
        if reason:
            raise ValueError(reason)
        if body.order_type in CONDITIONAL_TYPES and body.order_type not in LIVE_BROKER_STOP_TYPES:
            raise ValueError("На реальном счёте доступны рыночные, лимитные, стоп- и стоп-лимитные заявки")

    from app.services.pretrade.policy import assert_allowed, evaluate

    gate = evaluate(
        kind="manual_order",
        actor="human",
        user_id=str(user_id or user_email or "paper"),
        ticker=body.ticker,
        qty=float(body.quantity),
        price=float(body.limit_price or body.stop_price or 0.0),
        mode="paper",
        confirmed=bool(getattr(body, "risk_confirm", False)),
    )
    assert_allowed(gate)

    from app.services.ops_desk.live_hooks import reject_new_order

    px = float(body.limit_price or body.stop_price or 0.0)
    block = reject_new_order(
        ticker=body.ticker,
        side=body.side,
        qty=float(body.quantity),
        price=px,
        user_id=user_email or user_id or "paper",
        headlines=str(body.note or ""),
    )
    if block:
        raise ValueError(block)

    from app.services.execution.capability import resolve_execution_capability

    capability = await resolve_execution_capability(db, ticker=body.ticker, user_id=user_id)
    if not capability.execution_enabled:
        raise ValueError(capability.block_reason_ru or "Торговля этого инструмента сейчас недоступна.")

    rules = await get_symbol_trading_rules(body.ticker)
    ref_price = body.limit_price or body.stop_price
    validation_errors = validate_order_qty_price(
        qty=body.quantity,
        price=ref_price,
        rules=rules,
    )
    if validation_errors:
        raise ValueError("; ".join(validation_errors))

    if body.bracket and (body.bracket.stop_loss or body.bracket.take_profit):
        from app.services.execution.bracket_risk import align_with_engine

        entry = float(body.limit_price or body.stop_price or 0.0)
        sl0 = float(body.bracket.stop_loss or 0.0)
        atr = abs(entry - sl0) / 2.0 if entry and sl0 else 0.0
        if entry > 0 and atr > 0:
            chk = align_with_engine(
                ticker=body.ticker,
                side=body.side,
                entry=entry,
                atr=atr,
                stop_loss=body.bracket.stop_loss,
                take_profit=body.bracket.take_profit,
                portfolio_size=250.0,
            )
            if chk.ok:
                body.bracket.stop_loss = chk.stop_loss
                body.bracket.take_profit = chk.take_profit

    slippage: SlippageEstimate | None = None
    if body.order_type == "market":
        slippage = await estimate_slippage(body.ticker, body.quantity * (body.limit_price or 1))

    notional = body.quantity * (body.limit_price or body.stop_price or 0)
    fees = _fees_usd(notional) if notional > 0 else None

    order = ManualOrder(
        id=str(uuid.uuid4()),
        user_id=user_id,
        ticker=body.ticker.upper(),
        side=body.side,
        order_type=body.order_type,
        quantity=body.quantity,
        limit_price=body.limit_price,
        stop_price=body.stop_price,
        time_in_force=body.time_in_force,
        status="watching" if body.order_type in CONDITIONAL_TYPES else "pending",
        bracket_stop_loss=body.bracket.stop_loss if body.bracket else None,
        bracket_take_profit=body.bracket.take_profit if body.bracket else None,
        trailing_stop_pct=body.trailing_stop_pct,
        oco_sibling_price=body.oco_sibling_price,
        maneuver_id=body.maneuver_id,
        estimated_fees_usd=fees,
        slippage_warning=slippage.warning if slippage else None,
        note=body.note,
    )
    db.add(order)
    await db.flush()

    expiry_changes: dict[str, str] = {}
    if body.maneuver_id and (body.position_time_horizon or body.position_expiry_at):
        maneuver = None
        if user_id:
            from app.services.portfolio.user_scope import load_maneuver_for_user

            maneuver = await load_maneuver_for_user(db, user_id, body.maneuver_id)
        if maneuver is not None:
            expiry_changes = _apply_position_expiry(
                maneuver,
                time_horizon=body.position_time_horizon,
                expiry_at=body.position_expiry_at,
            )

    # On a real account stop / stop-limit rest at the broker, not in our watcher.
    if body.order_type in CONDITIONAL_TYPES and not (mode == "live" and body.order_type in LIVE_BROKER_STOP_TYPES):
        from app.services.orders.conditional_manager import register_conditional_order

        await register_conditional_order(db, order)
        await audit.log(
            db,
            action=AuditAction.ORDER_SUBMITTED,
            user_id=user_id,
            resource_type="manual_order",
            resource_id=order.id,
            details={
                "type": body.order_type,
                "status": "watching",
                "ticker": order.ticker,
                "position_expiry": expiry_changes or None,
            },
        )
        await db.commit()
        await db.refresh(order)
        return _to_out(order)

    req = OrderRequest(
        ticker=order.ticker,
        side=order.side,
        qty=order.quantity,
        order_type="market" if body.order_type == "market" else body.order_type,
        limit_price=body.limit_price,
        stop_price=body.stop_price,
        take_profit=body.bracket.take_profit if body.bracket else None,
        stop_loss=body.bracket.stop_loss if body.bracket else None,
        time_in_force=body.time_in_force,
        client_order_id=order.id,
        manual_order_context=ManualOrderExecutionContext(manual_order_id=order.id),
    )
    if not user_id:
        raise ValueError("user_id required for order execution")
    from app.services.trading_keys.user_executor import get_user_executor
    executor = await get_user_executor(
        db,
        user_id=user_id,
        ticker=order.ticker,
        account_mode=mode,
        user_email=user_email or '',
    )
    result = await executor.submit_order(req)

    order.status = result.status if result.status in ("filled", "submitted", "partially_filled") else "rejected"
    order.broker_order_id = result.broker_order_id
    order.fill_price = result.filled_price
    order.fill_quantity = result.filled_qty
    order.filled_at = result.filled_at
    order.error_message = result.error
    order.submitted_at = result.submitted_at

    if body.bracket and result.status == "filled":
        from app.services.orders.conditional_manager import register_bracket_watcher

        await register_bracket_watcher(db, order)

    await audit.log(
        db,
        action=AuditAction.ORDER_SUBMITTED,
        user_id=user_id,
        resource_type="manual_order",
        resource_id=order.id,
        details={
            "ticker": order.ticker,
            "side": order.side,
            "type": order.order_type,
            "status": order.status,
            "maneuver_id": body.maneuver_id,
            "position_expiry": expiry_changes or None,
        },
    )
    await db.commit()
    await db.refresh(order)
    logger.info("Manual order submitted", order_id=order.id, status=order.status, user=user_email)
    return _to_out(order)


async def modify_manual_order(
    db: AsyncSession,
    order_id: str,
    *,
    limit_price: float | None,
    quantity: float | None,
    user_id: str | None,
) -> ManualOrderOut:
    result = await db.execute(select(ManualOrder).where(ManualOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError("Order not found")
    if not user_id or order.user_id != user_id:
        raise ValueError("Order not found")
    if order.status not in ("pending", "submitted", "watching"):
        raise ValueError(f"Cannot modify order in status {order.status}")
    if order.order_type not in ("limit", "stop_limit"):
        raise ValueError("Only limit and stop-limit working orders can be modified")

    changes: dict[str, float] = {}
    if limit_price is not None:
        order.limit_price = limit_price
        changes["limit_price"] = limit_price
    if quantity is not None:
        order.quantity = quantity
        changes["quantity"] = quantity

    if order.limit_price and order.quantity:
        order.estimated_fees_usd = _fees_usd(order.limit_price * order.quantity)

    await audit.log(
        db,
        action=AuditAction.ORDER_SUBMITTED,
        user_id=user_id,
        resource_type="manual_order",
        resource_id=order.id,
        details={"action": "modify", **changes, "ticker": order.ticker},
    )
    await db.commit()
    await db.refresh(order)
    return _to_out(order)


async def cancel_manual_order(
    db: AsyncSession,
    order_id: str,
    *,
    user_id: str | None,
) -> ManualOrderOut:
    result = await db.execute(select(ManualOrder).where(ManualOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError("Order not found")
    if not user_id or order.user_id != user_id:
        raise ValueError("Order not found")
    if order.status in ("filled", "cancelled"):
        return _to_out(order)

    from app.services.orders.conditional_manager import unregister_conditional_order

    await unregister_conditional_order(db, order)
    order.status = "cancelled"
    await audit.log(
        db,
        action=AuditAction.ORDER_CANCELLED,
        user_id=user_id,
        resource_type="manual_order",
        resource_id=order.id,
        details={"ticker": order.ticker},
    )
    await db.commit()
    await db.refresh(order)
    return _to_out(order)


async def get_order_book(ticker: str) -> OrderBookSnapshot:
    return await fetch_order_book(ticker)


async def get_recent_trades(ticker: str, *, limit: int = 50) -> list:
    return await fetch_recent_trades(ticker, limit=limit)


def _to_out(order: ManualOrder) -> ManualOrderOut:
    from app.schemas.orders import BracketLeg

    bracket = None
    if order.bracket_stop_loss or order.bracket_take_profit:
        bracket = BracketLeg(
            stop_loss=order.bracket_stop_loss,
            take_profit=order.bracket_take_profit,
        )
    return ManualOrderOut(
        id=order.id,
        ticker=order.ticker,
        side=order.side,
        order_type=order.order_type,
        quantity=order.quantity,
        limit_price=order.limit_price,
        stop_price=order.stop_price,
        time_in_force=order.time_in_force,
        status=order.status,
        bracket=bracket,
        trailing_stop_pct=order.trailing_stop_pct,
        maneuver_id=order.maneuver_id,
        broker_order_id=order.broker_order_id,
        fill_price=order.fill_price,
        fill_quantity=order.fill_quantity,
        estimated_fees_usd=order.estimated_fees_usd,
        slippage_warning=order.slippage_warning,
        sibling_order_id=order.sibling_order_id,
        submitted_at=order.submitted_at,
        filled_at=order.filled_at,
        error_message=order.error_message,
    )
