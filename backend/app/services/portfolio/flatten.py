"""Flatten (close-all) service for the paper book.

The big red STOP / "Закрыть все позиции" operator action must actually free
exposure. In paper mode this:
  * CLOSES every open position (EXECUTING / FILLED) — realizing mark-to-market
    P&L at the latest known price and stamping ``realized_pnl`` + ``CLOSED``,
  * CANCELS every APPROVED-but-not-yet-filled maneuver so no new order opens.

Once positions are CLOSED/CANCELLED they no longer count toward portfolio
exposure (see ``position_limits`` / ``metrics`` which only sum EXECUTING+FILLED),
so freed budget immediately unblocks new approvals.

Live flattening is intentionally NOT handled here: closing a real broker book
requires routing offsetting orders through the executor, so we refuse rather
than pretend. The endpoint surfaces that as a clear 409.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import AuditLog, Maneuver, ManeuverStatus, User
from app.services.portfolio.position_analytics import latest_prices, unrealized_net_pnl

logger = get_logger(__name__)

# Statuses that represent capital that is (or is about to be) deployed.
_OPEN_STATUSES = (
    ManeuverStatus.APPROVED,
    ManeuverStatus.EXECUTING,
    ManeuverStatus.FILLED,
)
# Positions that hold live exposure (vs. APPROVED which has not filled yet).
_HELD_STATUSES = (ManeuverStatus.EXECUTING, ManeuverStatus.FILLED)


class LiveFlattenNotSupported(RuntimeError):
    """Raised when a flatten is requested while live trading is unlocked."""


@dataclass
class ClosedPosition:
    id: str
    ticker: str
    direction: str
    status_before: str
    action: str  # "closed" | "cancelled"
    size_usd: float
    realized_pnl: float | None = None
    close_price: float | None = None


@dataclass
class CloseAllResult:
    mode: str
    closed_count: int = 0
    cancelled_count: int = 0
    realized_pnl_total: float = 0.0
    freed_exposure_usd: float = 0.0
    message: str = ""
    positions: list[ClosedPosition] = field(default_factory=list)


async def close_all_positions(
    db: AsyncSession,
    email: str | None,
    *,
    reason: str = "operator flatten",
) -> CloseAllResult:
    """Close all open paper positions and cancel approved orders. Frees exposure."""
    if settings.live_trading_unlocked:
        raise LiveFlattenNotSupported(
            "Плоское закрытие доступно только в paper-режиме. "
            "Live-книга закрывается через брокера/kill-switch."
        )

    from app.services.portfolio.user_scope import get_user_by_email, maneuvers_for_user

    user = await get_user_by_email(db, email) if email else None
    if user is None:
        return CloseAllResult(mode="paper", message="User not found.")

    result = await db.execute(
        maneuvers_for_user(user.id).where(Maneuver.status.in_(_OPEN_STATUSES))
    )
    maneuvers = list(result.scalars().all())

    if not maneuvers:
        return CloseAllResult(
            mode="paper",
            message="Нет открытых позиций для закрытия.",
        )

    prices = await latest_prices(db, [m.ticker for m in maneuvers])
    now = datetime.now(timezone.utc)

    closed: list[ClosedPosition] = []
    realized_total = 0.0
    freed_exposure = 0.0

    for m in maneuvers:
        status_before = str(getattr(m.status, "value", m.status))
        size_usd = float(m.position_size_usd or 0.0)

        if m.status == ManeuverStatus.APPROVED:
            # Paper/approved ideas that never filled must still close into the book
            # (ЗАКРЫТЫЕ + audit), not vanish as CANCELLED with no P&L trail.
            price = prices.get(m.ticker.upper())
            realized = unrealized_net_pnl(m, price)
            if realized is None:
                realized = 0.0
            from app.services.portfolio.entry_snapshot import finalize_close_metadata

            await finalize_close_metadata(
                db,
                m,
                exit_reason="manual_flatten",
                exit_price=price,
                realized_pnl=realized,
            )
            m.status = ManeuverStatus.CLOSED
            realized_total += realized
            freed_exposure += size_usd
            closed.append(
                ClosedPosition(
                    id=m.id,
                    ticker=m.ticker,
                    direction=str(m.direction),
                    status_before=status_before,
                    action="closed",
                    size_usd=round(size_usd, 2),
                    realized_pnl=round(realized, 2),
                    close_price=round(float(price), 4) if price else None,
                )
            )
            continue

        price = prices.get(m.ticker.upper())
        realized = unrealized_net_pnl(m, price)
        if realized is None:
            realized = 0.0
        from app.services.portfolio.entry_snapshot import finalize_close_metadata

        await finalize_close_metadata(
            db,
            m,
            exit_reason="manual",
            exit_price=price,
            realized_pnl=realized,
        )
        m.status = ManeuverStatus.CLOSED
        try:
            owner_id = None
            if m.report is not None:
                owner_id = m.report.created_by
            if owner_id and price is not None:
                from app.services.portfolio.lot_ledger import close_maneuver_lots
                from app.services.robot.plan import complete_plans_for_maneuver

                await close_maneuver_lots(
                    db,
                    user_id=owner_id,
                    maneuver_id=m.id,
                    ticker=m.ticker,
                    direction=str(getattr(m.direction, "value", m.direction)),
                    exit_price=float(price),
                    reason="flatten",
                )
                await complete_plans_for_maneuver(db, maneuver_id=m.id, reason="flatten")
        except Exception as exc:
            logger.warning("flatten lot/plan close failed", maneuver_id=m.id, error=str(exc)[:200])
        realized_total += realized
        freed_exposure += size_usd
        closed.append(
            ClosedPosition(
                id=m.id,
                ticker=m.ticker,
                direction=str(m.direction),
                status_before=status_before,
                action="closed",
                size_usd=round(size_usd, 2),
                realized_pnl=round(realized, 2),
                close_price=round(float(price), 4) if price else None,
            )
        )

    closed_count = sum(1 for c in closed if c.action == "closed")
    cancelled_count = sum(1 for c in closed if c.action == "cancelled")

    user = None
    if email:
        user_result = await db.execute(select(User).where(User.email == email))
        user = user_result.scalar_one_or_none()

    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action="positions_flatten",
            resource_type="portfolio",
            resource_id=None,
            details={
                "reason": reason,
                "closed": closed_count,
                "cancelled": cancelled_count,
                "realized_pnl_total": round(realized_total, 2),
                "freed_exposure_usd": round(freed_exposure, 2),
                "tickers": [c.ticker for c in closed],
            },
        )
    )
    await db.commit()
    from app.services.portfolio.metrics import clear_portfolio_metrics_holdback

    await clear_portfolio_metrics_holdback(email)

    logger.info(
        "Paper positions flattened",
        closed=closed_count,
        cancelled=cancelled_count,
        realized_pnl=round(realized_total, 2),
        freed_exposure=round(freed_exposure, 2),
        at=now.isoformat(),
    )

    parts = []
    if closed_count:
        parts.append(f"закрыто позиций: {closed_count}")
    if cancelled_count:
        parts.append(f"отменено ордеров: {cancelled_count}")
    summary = ", ".join(parts) if parts else "нет изменений"
    message = (
        f"Paper-книга сброшена ({summary}). "
        f"Реализованный P&L: ${realized_total:,.0f}. "
        f"Освобождено экспозиции: ${freed_exposure:,.0f}."
    )

    return CloseAllResult(
        mode="paper",
        closed_count=closed_count,
        cancelled_count=cancelled_count,
        realized_pnl_total=round(realized_total, 2),
        freed_exposure_usd=round(freed_exposure, 2),
        message=message,
        positions=closed,
    )
