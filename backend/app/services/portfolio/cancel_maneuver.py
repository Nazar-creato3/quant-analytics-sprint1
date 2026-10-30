"""Cancel or close a single maneuver (paper book).

Unlike bulk flatten (``close_all_positions``), this targets one maneuver by id
so the operator can withdraw an approved proposal or close one position without
affecting the rest of the book.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import AuditLog, Maneuver, ManeuverStatus, User
from app.services.portfolio.flatten import LiveFlattenNotSupported
from app.services.portfolio.position_analytics import latest_prices, unrealized_net_pnl
from app.utils.audit import AuditAction

logger = get_logger(__name__)

_CANCELLABLE_STATUSES = (
    ManeuverStatus.PENDING,
    ManeuverStatus.APPROVED,
)
_CLOSEABLE_STATUSES = (
    ManeuverStatus.EXECUTING,
    ManeuverStatus.FILLED,
)


class ManeuverNotCancellable(RuntimeError):
    """Raised when the maneuver is in a terminal or unsupported state."""

    def __init__(self, maneuver_id: str, status: str) -> None:
        super().__init__(f"Maneuver {maneuver_id} in status '{status}' cannot be cancelled.")
        self.maneuver_id = maneuver_id
        self.status = status


class ManeuverNotFound(RuntimeError):
    """Raised when the maneuver id does not exist."""

    def __init__(self, maneuver_id: str) -> None:
        super().__init__(f"Maneuver {maneuver_id} not found.")
        self.maneuver_id = maneuver_id


@dataclass
class CancelManeuverResult:
    maneuver_id: str
    ticker: str
    status_before: str
    status_after: str
    action: str  # "cancelled" | "closed"
    size_usd: float
    realized_pnl: float | None = None
    message: str = ""


async def cancel_maneuver(
    db: AsyncSession,
    maneuver_id: str,
    email: str | None,
    *,
    reason: str = "operator cancel",
    note: str | None = None,
    staff_include_orphans: bool = False,
) -> CancelManeuverResult:
    """Cancel one maneuver or close one open paper position."""
    from app.services.portfolio.user_scope import get_user_by_email, load_maneuver_for_user

    user = None
    if email:
        user_result = await db.execute(select(User).where(User.email == email))
        user = user_result.scalar_one_or_none()

    if user is None:
        raise ManeuverNotFound(maneuver_id)

    maneuver = await load_maneuver_for_user(
        db,
        user.id,
        maneuver_id,
        staff_include_orphans=staff_include_orphans,
    )
    if maneuver is None:
        raise ManeuverNotFound(maneuver_id)

    status_before = str(getattr(maneuver.status, "value", maneuver.status))
    size_usd = float(maneuver.position_size_usd or 0.0)

    if maneuver.status in _CANCELLABLE_STATUSES:
        maneuver.status = ManeuverStatus.CANCELLED
        action = "cancelled"
        realized_pnl: float | None = None
        message = f"Маневр {maneuver.ticker} отменён."
    elif maneuver.status in _CLOSEABLE_STATUSES:
        if settings.live_trading_unlocked:
            raise LiveFlattenNotSupported(
                "Закрытие отдельной позиции доступно только в paper-режиме."
            )
        prices = await latest_prices(db, [maneuver.ticker])
        price = prices.get(maneuver.ticker.upper())
        realized = unrealized_net_pnl(maneuver, price)
        if realized is None:
            realized = 0.0
        from app.services.portfolio.entry_snapshot import finalize_close_metadata

        await finalize_close_metadata(
            db,
            maneuver,
            exit_reason="manual",
            exit_price=price,
            realized_pnl=realized,
        )
        maneuver.status = ManeuverStatus.CLOSED
        try:
            if user and price is not None:
                from app.services.portfolio.lot_ledger import close_maneuver_lots
                from app.services.robot.plan import complete_plans_for_maneuver

                await close_maneuver_lots(
                    db,
                    user_id=user.id,
                    maneuver_id=maneuver.id,
                    ticker=maneuver.ticker,
                    direction=str(getattr(maneuver.direction, "value", maneuver.direction)),
                    exit_price=float(price),
                    reason="manual",
                )
                await complete_plans_for_maneuver(db, maneuver_id=maneuver.id, reason="manual")
        except Exception as lot_exc:
            logger.warning("lot_close_on_cancel_failed", maneuver_id=maneuver.id, error=str(lot_exc)[:160])
        try:
            from app.services.forecast.feature_kill import blocks_from_maneuver_meta, record_losing_blocks

            meta = getattr(maneuver, "signal_meta", None) or {}
            if not isinstance(meta, dict):
                meta = {}
            record_losing_blocks(blocks_from_maneuver_meta(meta), pnl=float(realized or 0.0))
        except Exception as exc:
            logger.warning("feature kill record failed", maneuver_id=maneuver.id, error=str(exc)[:200])
        action = "closed"
        realized_pnl = round(realized, 2)
        message = (
            f"Позиция {maneuver.ticker} закрыта (paper). "
            f"Реализованный P&L: ${realized_pnl:,.0f}."
        )
    else:
        raise ManeuverNotCancellable(maneuver_id, status_before)

    status_after = str(getattr(maneuver.status, "value", maneuver.status))
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=AuditAction.MANEUVER_CANCELLED,
            resource_type="maneuver",
            resource_id=maneuver_id,
            details={
                "reason": reason,
                "note": note,
                "ticker": maneuver.ticker,
                "status_before": status_before,
                "status_after": status_after,
                "action": action,
                "size_usd": round(size_usd, 2),
                "realized_pnl": realized_pnl,
            },
        )
    )
    await db.commit()
    from app.services.portfolio.metrics import clear_portfolio_metrics_holdback

    await clear_portfolio_metrics_holdback(email)

    logger.info(
        "Maneuver cancelled individually",
        maneuver_id=maneuver_id,
        ticker=maneuver.ticker,
        action=action,
        status_before=status_before,
        status_after=status_after,
    )

    return CancelManeuverResult(
        maneuver_id=maneuver_id,
        ticker=maneuver.ticker,
        status_before=status_before,
        status_after=status_after,
        action=action,
        size_usd=round(size_usd, 2),
        realized_pnl=realized_pnl,
        message=message,
    )
