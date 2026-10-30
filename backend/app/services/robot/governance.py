"""Governance — multi-sig flatten / pause with audit log."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus, new_uuid
from app.db.robot_models import GovernanceLog, RobotPlan
from app.services.portfolio.expire_disposition import is_paper_maneuver
from app.services.portfolio.position_analytics import latest_prices
from app.services.robot.position_closer import close_maneuver_locked

logger = get_logger(__name__)


async def request_flatten(
    db: AsyncSession,
    *,
    initiated_by: str,
    reason: str,
    plan_ids: list[str] | None = None,
    required_approvals: int = 2,
) -> GovernanceLog:
    log = GovernanceLog(
        id=new_uuid(),
        action="flatten",
        status="pending",
        initiated_by=initiated_by,
        approved_by=[],
        required_approvals=max(1, int(required_approvals)),
        reason=reason or "emergency flatten",
        affected_plans=plan_ids or [],
        created_at=datetime.now(timezone.utc),
    )
    db.add(log)
    await db.flush()
    logger.info("governance_flatten_requested", log_id=log.id, by=initiated_by)
    return log


async def approve_governance(
    db: AsyncSession,
    *,
    log_id: str,
    approver_id: str,
) -> dict[str, Any]:
    log = await db.get(GovernanceLog, log_id)
    if log is None:
        return {"ok": False, "error": "not_found"}
    if log.status not in {"pending", "approved"}:
        return {"ok": False, "error": f"status_{log.status}"}

    approved = list(log.approved_by or [])
    if approver_id in approved:
        return {"ok": True, "status": log.status, "approvals": len(approved), "duplicate": True}
    if approver_id == log.initiated_by and log.required_approvals > 1:
        # initiator does not count toward multi-sig
        pass
    approved.append(approver_id)
    log.approved_by = approved
    flag_modified(log, "approved_by")

    if len(approved) < int(log.required_approvals):
        await db.flush()
        return {
            "ok": True,
            "status": "pending",
            "approvals": len(approved),
            "required": log.required_approvals,
        }

    log.status = "approved"
    executed = await _execute_flatten(db, log=log)
    log.status = "executed"
    log.executed_at = datetime.now(timezone.utc)
    await db.flush()
    return {
        "ok": True,
        "status": "executed",
        "approvals": len(approved),
        "closed": executed.get("closed", 0),
    }


async def _execute_flatten(db: AsyncSession, *, log: GovernanceLog) -> dict[str, Any]:
    plan_ids = [str(x) for x in (log.affected_plans or [])]
    closed = 0
    if plan_ids:
        res = await db.execute(select(RobotPlan).where(RobotPlan.id.in_(plan_ids)))
        plans = list(res.scalars().all())
    else:
        res = await db.execute(
            select(RobotPlan).where(
                RobotPlan.user_id == log.initiated_by,
                RobotPlan.status == "active",
            )
        )
        plans = list(res.scalars().all())

    tickers = [p.ticker for p in plans]
    prices = await latest_prices(db, tickers) if tickers else {}
    for plan in plans:
        if not plan.maneuver_id:
            plan.status = "cancelled"
            continue
        m = await db.get(Maneuver, plan.maneuver_id)
        if m is None or m.status not in (ManeuverStatus.FILLED, ManeuverStatus.EXECUTING):
            plan.status = "cancelled"
            continue
        if not is_paper_maneuver(m):
            # Live flatten still needs venue path — log only
            logger.warning("governance_live_flatten_skipped", maneuver_id=m.id)
            continue
        mark = prices.get(plan.ticker.upper()) or float(m.fill_price or m.entry_price or 0)
        if mark <= 0:
            continue
        r = await close_maneuver_locked(
            db,
            maneuver_id=m.id,
            user_id=plan.user_id,
            exit_price=float(mark),
            reason="governance_flatten",
            plan_id=plan.id,
        )
        if r.closed:
            closed += 1
    return {"closed": closed}


def governance_to_dict(log: GovernanceLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "action": log.action,
        "status": log.status,
        "initiated_by": log.initiated_by,
        "approved_by": log.approved_by or [],
        "required_approvals": log.required_approvals,
        "reason": log.reason,
        "affected_plans": log.affected_plans or [],
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "executed_at": log.executed_at.isoformat() if log.executed_at else None,
    }
