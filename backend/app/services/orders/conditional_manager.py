"""Client-side conditional order manager for OCO/trailing stops (spec B.2)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import ConditionalOrderWatch, ManualOrder
from app.services.execution.adapter import OrderRequest

logger = get_logger(__name__)


async def register_conditional_order(db: AsyncSession, order: ManualOrder) -> ConditionalOrderWatch:
    watch = ConditionalOrderWatch(
        id=str(uuid.uuid4()),
        manual_order_id=order.id,
        user_id=order.user_id,
        ticker=order.ticker,
        trigger_type=order.order_type,
        trigger_price=order.stop_price or order.oco_sibling_price,
        trail_distance_pct=order.trailing_stop_pct,
        status="watching",
        peak_price=None,
    )
    db.add(watch)
    await db.flush()
    logger.info("Conditional order registered", watch_id=watch.id, type=order.order_type)
    return watch


async def register_bracket_watcher(db: AsyncSession, parent: ManualOrder) -> None:
    if not parent.bracket_stop_loss and not parent.bracket_take_profit:
        return
    try:
        from app.services.execution.bracket_risk import align_with_engine

        entry = float(parent.fill_price or parent.limit_price or 0.0)
        sl = float(parent.bracket_stop_loss or 0.0)
        atr = abs(entry - sl) / 2.0 if entry and sl else 0.0
        if entry > 0 and atr > 0:
            chk = align_with_engine(
                ticker=parent.ticker,
                side=parent.side,
                entry=entry,
                atr=atr,
                stop_loss=parent.bracket_stop_loss,
                take_profit=parent.bracket_take_profit,
                portfolio_size=250.0,
            )
            if chk.ok:
                parent.bracket_stop_loss = chk.stop_loss
                parent.bracket_take_profit = chk.take_profit
    except Exception as exc:
        logger.debug("bracket_align_skip", error=str(exc)[:120])
    watch = ConditionalOrderWatch(
        id=str(uuid.uuid4()),
        manual_order_id=parent.id,
        user_id=parent.user_id,
        ticker=parent.ticker,
        trigger_type="bracket",
        trigger_price=parent.bracket_stop_loss or parent.bracket_take_profit,
        trail_distance_pct=None,
        status="watching",
        peak_price=parent.fill_price,
    )
    db.add(watch)
    await db.flush()


async def unregister_conditional_order(db: AsyncSession, order: ManualOrder) -> None:
    result = await db.execute(
        select(ConditionalOrderWatch).where(
            ConditionalOrderWatch.manual_order_id == order.id,
            ConditionalOrderWatch.status == "watching",
        )
    )
    for watch in result.scalars().all():
        watch.status = "cancelled"


async def poll_conditional_orders(db: AsyncSession) -> int:
    """
    Poll live prices and trigger conditional orders.

    Called from background task or on-demand — submits broker orders when conditions met.
    """
    result = await db.execute(
        select(ConditionalOrderWatch).where(ConditionalOrderWatch.status == "watching")
    )
    watches = result.scalars().all()
    triggered = 0

    for watch in watches:
        try:
            from app.services.market_data.client import get_latest_quote_resolved

            quote = await get_latest_quote_resolved(watch.ticker)
            price = float(quote.get("price") or quote.get("bid") or 0)
            if price <= 0:
                continue

            order_result = await db.execute(
                select(ManualOrder).where(ManualOrder.id == watch.manual_order_id)
            )
            parent = order_result.scalar_one_or_none()
            if not parent or parent.status in ("filled", "cancelled"):
                watch.status = "cancelled"
                continue

            should_trigger = False
            if watch.trigger_type == "oco":
                if watch.trigger_price and (
                    (parent.side == "buy" and price >= watch.trigger_price)
                    or (parent.side == "sell" and price <= watch.trigger_price)
                ):
                    should_trigger = True
            elif watch.trigger_type == "stop":
                if watch.trigger_price and (
                    (parent.side == "buy" and price >= watch.trigger_price)
                    or (parent.side == "sell" and price <= watch.trigger_price)
                ):
                    should_trigger = True
            elif watch.trigger_type == "stop_limit":
                if watch.trigger_price and (
                    (parent.side == "buy" and price >= watch.trigger_price)
                    or (parent.side == "sell" and price <= watch.trigger_price)
                ):
                    should_trigger = True
            elif watch.trigger_type == "trailing_stop":
                peak = watch.peak_price or price
                if parent.side == "buy":
                    peak = max(peak, price)
                    watch.peak_price = peak
                    trail = watch.trail_distance_pct or 1.0
                    stop_level = peak * (1 - trail / 100)
                    if price <= stop_level:
                        should_trigger = True
                else:
                    peak = min(peak, price) if watch.peak_price else price
                    watch.peak_price = peak
                    trail = watch.trail_distance_pct or 1.0
                    stop_level = peak * (1 + trail / 100)
                    if price >= stop_level:
                        should_trigger = True
            elif watch.trigger_type == "bracket":
                if parent.bracket_take_profit and (
                    (parent.side == "buy" and price >= parent.bracket_take_profit)
                    or (parent.side == "sell" and price <= parent.bracket_take_profit)
                ):
                    should_trigger = True
                elif parent.bracket_stop_loss and (
                    (parent.side == "buy" and price <= parent.bracket_stop_loss)
                    or (parent.side == "sell" and price >= parent.bracket_stop_loss)
                ):
                    should_trigger = True

            if not should_trigger:
                continue

            is_entry_stop = watch.trigger_type in ("stop", "stop_limit")
            if is_entry_stop:
                exec_side = parent.side
                exec_type = "limit" if watch.trigger_type == "stop_limit" else "market"
                exec_limit = parent.limit_price if watch.trigger_type == "stop_limit" else None
            else:
                exec_side = "sell" if parent.side == "buy" else "buy"
                exec_type = "market"
                exec_limit = None

            req = OrderRequest(
                ticker=watch.ticker,
                side=exec_side,
                qty=parent.quantity,
                order_type=exec_type,
                limit_price=exec_limit,
            )
            from app.services.execution.adapter import PaperExecutor
            from app.services.trading_keys.user_executor import get_user_executor

            if parent.user_id:
                executor = await get_user_executor(
                    db,
                    user_id=parent.user_id,
                    ticker=watch.ticker,
                )
            else:
                executor = PaperExecutor()
            fill = await executor.submit_order(req)

            if is_entry_stop:
                parent.status = fill.status if fill.status in ("filled", "submitted") else "rejected"
                parent.broker_order_id = fill.broker_order_id
                parent.fill_price = fill.filled_price
                parent.fill_quantity = fill.filled_qty
                parent.filled_at = fill.filled_at or datetime.now(timezone.utc)
                parent.submitted_at = fill.submitted_at
                watch.status = "triggered"
                if fill.status == "filled" and (parent.bracket_stop_loss or parent.bracket_take_profit):
                    await register_bracket_watcher(db, parent)
                triggered += 1
                logger.info(
                    "Stop order triggered",
                    watch_id=watch.id,
                    ticker=watch.ticker,
                    price=price,
                )
                continue

            sibling = ManualOrder(
                id=str(uuid.uuid4()),
                user_id=parent.user_id,
                ticker=parent.ticker,
                side=exec_side,
                order_type="market",
                quantity=parent.quantity,
                time_in_force="day",
                status=fill.status,
                broker_order_id=fill.broker_order_id,
                fill_price=fill.filled_price,
                fill_quantity=fill.filled_qty,
                filled_at=fill.filled_at or datetime.now(timezone.utc),
                maneuver_id=parent.maneuver_id,
            )
            db.add(sibling)
            parent.sibling_order_id = sibling.id
            parent.status = "filled"
            watch.status = "triggered"
            triggered += 1
            logger.info(
                "Conditional order triggered",
                watch_id=watch.id,
                ticker=watch.ticker,
                price=price,
            )
        except Exception as exc:
            logger.warning("Conditional poll error", watch_id=watch.id, error=str(exc))

    if triggered:
        await db.commit()
    return triggered
