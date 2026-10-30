"""Unified position closer — single source of truth for flattens.

All barrier/robot/cancel/kill paths MUST call close_maneuver_locked.
Uses SELECT … FOR UPDATE on maneuvers to prevent double-close races.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus
from app.services.portfolio.entry_snapshot import finalize_close_metadata
from app.services.portfolio.lot_ledger import close_maneuver_lots
from app.services.portfolio.position_analytics import unrealized_net_pnl
from app.services.robot.plan import complete_plans_for_maneuver

logger = get_logger(__name__)

_OPEN = (ManeuverStatus.FILLED, ManeuverStatus.EXECUTING)


@dataclass
class CloseResult:
    closed: bool
    already_closed: bool
    maneuver_id: str
    reason: str
    exit_price: float | None = None
    realized_pnl: float | None = None
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "closed": self.closed,
            "already_closed": self.already_closed,
            "maneuver_id": self.maneuver_id,
            "reason": self.reason,
            "exit_price": self.exit_price,
            "realized_pnl": self.realized_pnl,
            "idempotency_key": self.idempotency_key,
        }


async def close_maneuver_locked(
    db: AsyncSession,
    *,
    maneuver_id: str,
    user_id: str | None,
    exit_price: float,
    reason: str,
    level_id: str | None = None,
    plan_id: str | None = None,
    cancel_open_levels: bool = True,
) -> CloseResult:
    """Atomically close one open maneuver + linked lots + robot plans.

    Concurrent callers: only the first succeeds; others get already_closed=True.
    """
    key = f"close:{maneuver_id}:{reason}:{level_id or '-'}"
    stmt = (
        select(Maneuver)
        .where(Maneuver.id == maneuver_id)
        .options(joinedload(Maneuver.report))
        .with_for_update()
    )
    result = await db.execute(stmt)
    maneuver = result.scalar_one_or_none()
    if maneuver is None:
        logger.warning("position_closer_missing", maneuver_id=maneuver_id)
        return CloseResult(
            closed=False,
            already_closed=True,
            maneuver_id=maneuver_id,
            reason=reason,
            idempotency_key=key,
        )

    if maneuver.status not in _OPEN:
        return CloseResult(
            closed=False,
            already_closed=True,
            maneuver_id=maneuver_id,
            reason=reason,
            exit_price=float(maneuver.exit_price) if maneuver.exit_price else None,
            realized_pnl=float(maneuver.realized_pnl) if maneuver.realized_pnl is not None else None,
            idempotency_key=key,
        )

    px = float(exit_price)
    realized = unrealized_net_pnl(maneuver, px)
    if realized is None:
        realized = 0.0

    await finalize_close_metadata(
        db,
        maneuver,
        exit_reason=reason,
        exit_price=px,
        realized_pnl=realized,
    )
    maneuver.status = ManeuverStatus.CLOSED

    owner = user_id
    if owner is None and maneuver.report is not None:
        owner = maneuver.report.created_by

    if owner:
        try:
            await close_maneuver_lots(
                db,
                user_id=owner,
                maneuver_id=maneuver.id,
                ticker=maneuver.ticker,
                direction=str(getattr(maneuver.direction, "value", maneuver.direction)),
                exit_price=px,
                reason=reason,
            )
        except Exception as exc:
            logger.warning(
                "position_closer_lot_failed",
                maneuver_id=maneuver_id,
                error=str(exc)[:200],
            )

    try:
        await complete_plans_for_maneuver(db, maneuver_id=maneuver.id, reason=reason)
    except Exception as exc:
        logger.warning(
            "position_closer_plan_complete_failed",
            maneuver_id=maneuver_id,
            error=str(exc)[:160],
        )

    if cancel_open_levels and plan_id:
        try:
            from app.db.robot_models import RobotPlan

            plan = await db.get(RobotPlan, plan_id)
            if plan is not None and plan.levels:
                now = datetime.now(timezone.utc).isoformat()
                levels = list(plan.levels)
                for lv in levels:
                    st = str(lv.get("status") or "")
                    if st in {"watching", "pending", "armed", "triggered"}:
                        if level_id and str(lv.get("id")) == str(level_id):
                            lv["status"] = "filled"
                            lv["fill_price"] = px
                            lv["filled_at"] = now
                            lv["exit_reason"] = reason
                        else:
                            lv["status"] = "cancelled"
                            lv["cancelled_at"] = now
                plan.levels = levels
                plan.updated_at = datetime.now(timezone.utc)
        except Exception as exc:
            logger.warning(
                "position_closer_levels_failed",
                plan_id=plan_id,
                error=str(exc)[:160],
            )

    try:
        from app.services.robot.reconcile import reconcile_maneuver_with_ledger

        if owner:
            await reconcile_maneuver_with_ledger(db, maneuver_id=maneuver.id, user_id=owner)
    except Exception as exc:
        logger.warning(
            "position_closer_reconcile_failed",
            maneuver_id=maneuver_id,
            error=str(exc)[:160],
        )

    logger.info(
        "position_closed",
        maneuver_id=maneuver_id,
        reason=reason,
        exit_price=px,
        realized_pnl=realized,
        level_id=level_id,
    )
    return CloseResult(
        closed=True,
        already_closed=False,
        maneuver_id=maneuver_id,
        reason=reason,
        exit_price=px,
        realized_pnl=realized,
        idempotency_key=key,
    )
