"""Auto-close / cancel when the stated holding period ends."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.logging import get_logger
from app.db.models import ExecutionOrder, Maneuver, ManeuverReport, ManeuverStatus
from app.services.portfolio.audit_trigger import enqueue_position_audits_for_users
from app.services.portfolio.entry_snapshot import finalize_close_metadata
from app.services.portfolio.expire_disposition import expire_disposition
from app.services.portfolio.position_analytics import (
    latest_prices,
    should_auto_close_on_horizon,
    unrealized_net_pnl,
)

logger = get_logger(__name__)

OPEN_BOOK_STATUSES = (
    ManeuverStatus.APPROVED,
    ManeuverStatus.EXECUTING,
    ManeuverStatus.FILLED,
)


async def _load_open_book_maneuvers(db: AsyncSession, *, user_id: str | None = None) -> list[Maneuver]:
    if user_id is not None:
        from app.services.portfolio.user_scope import maneuvers_for_user

        stmt = maneuvers_for_user(user_id).where(Maneuver.status.in_(OPEN_BOOK_STATUSES))
    else:
        stmt = select(Maneuver).where(Maneuver.status.in_(OPEN_BOOK_STATUSES))
    stmt = stmt.options(joinedload(Maneuver.report))
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


def _owner_user_ids(maneuvers: list[Maneuver]) -> set[str]:
    owners: set[str] = set()
    for maneuver in maneuvers:
        report = maneuver.report
        owner = report.created_by if report is not None else None
        if owner:
            owners.add(owner)
    return owners


async def _cancel_live_orders(db: AsyncSession, maneuver: Maneuver) -> None:
    result = await db.execute(
        select(ExecutionOrder).where(ExecutionOrder.maneuver_id == maneuver.id)
    )
    orders = list(result.scalars().all())
    ids = [o.broker_order_id for o in orders if o.broker_order_id]
    if not ids:
        return
    try:
        from app.services.execution.adapter import AlpacaExecutor

        broker = AlpacaExecutor()
        for oid in ids:
            try:
                await broker.cancel_order(oid)
            except Exception as exc:
                logger.warning("live_expiry_cancel_failed", order_id=oid, error=str(exc)[:160])
    except Exception as exc:
        logger.warning("live_expiry_cancel_broker_unavailable", error=str(exc)[:160])


async def _close_expired(db: AsyncSession, loaded: list[Maneuver], *, extra_owners: set[str] | None = None) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    maneuvers = [m for m in loaded if should_auto_close_on_horizon(m, now)]
    if not maneuvers:
        return {"closed": 0, "cancelled_live": 0}

    prices = await latest_prices(db, [m.ticker for m in maneuvers])
    closed = 0
    cancelled_live = 0
    audit_owners: set[str] = set()
    for m in maneuvers:
        action = expire_disposition(m)
        if action == "cancel_live_no_audit":
            await _cancel_live_orders(db, m)
            m.status = ManeuverStatus.CANCELLED
            m.exit_reason = "expiration_unfilled"
            cancelled_live += 1
            continue
        price = prices.get(m.ticker.upper())
        # Always mark-to-market when we have an entry reference + exit price.
        # (Previously paper-without-fill forced realized=0 → closed "+$0" with no audit signal.)
        realized = unrealized_net_pnl(m, price)
        if realized is None:
            realized = 0.0
        exit_px = price
        await finalize_close_metadata(
            db,
            m,
            exit_reason="expiration",
            exit_price=exit_px,
            realized_pnl=realized,
        )
        # Flatten leftover venue OCO / brackets so expiry is not a one-legged book.
        await _cancel_live_orders(db, m)
        m.status = ManeuverStatus.CLOSED
        closed += 1
        report = m.report
        owner = report.created_by if report is not None else None
        if owner:
            audit_owners.add(owner)
            try:
                from app.services.portfolio.lot_ledger import close_maneuver_lots
                from app.services.robot.plan import complete_plans_for_maneuver

                if exit_px is not None:
                    await close_maneuver_lots(
                        db,
                        user_id=owner,
                        maneuver_id=m.id,
                        ticker=m.ticker,
                        direction=str(getattr(m.direction, "value", m.direction)),
                        exit_price=float(exit_px),
                        reason="expiration",
                    )
                await complete_plans_for_maneuver(db, maneuver_id=m.id, reason="expiration")
            except Exception as exc:
                logger.warning("expiration lot/plan close failed", maneuver_id=m.id, error=str(exc)[:200])

    await db.commit()
    logger.info("expiration_closes", closed=closed, cancelled_live=cancelled_live)

    if closed:
        if extra_owners:
            audit_owners |= extra_owners
        if audit_owners:
            await enqueue_position_audits_for_users(db, audit_owners)

    return {"closed": closed, "cancelled_live": cancelled_live}


async def close_expired_positions(db: AsyncSession) -> dict[str, int]:
    loaded = await _load_open_book_maneuvers(db)
    return await _close_expired(db, loaded)


async def close_expired_for_user(db: AsyncSession, user_id: str) -> dict[str, int]:
    loaded = await _load_open_book_maneuvers(db, user_id=user_id)
    return await _close_expired(db, loaded, extra_owners={user_id})


async def users_with_expiration_closes_pending_audit(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(ManeuverReport.created_by)
        .join(Maneuver, Maneuver.report_id == ManeuverReport.id)
        .where(
            Maneuver.status == ManeuverStatus.CLOSED,
            Maneuver.exit_reason == "expiration",
            ManeuverReport.created_by.isnot(None),
        )
        .distinct()
    )
    return [row[0] for row in result.all() if row[0]]
