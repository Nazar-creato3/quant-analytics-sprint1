"""StrategySession lifecycle — entry → scales → flat with override log."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import get_logger
from app.db.models import new_uuid
from app.db.robot_models import RobotPlan, StrategySession

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def plan_version_hash(plan: RobotPlan) -> str:
    payload = {
        "levels": plan.levels,
        "side": plan.side,
        "mode": plan.mode,
        "plan_type": getattr(plan, "plan_type", "custom"),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def ensure_session(
    db: AsyncSession, *, plan: RobotPlan, entry_reason: str = "monitor"
) -> StrategySession:
    if plan.session_id:
        sess = await db.get(StrategySession, plan.session_id)
        if sess is not None and sess.status == "active":
            return sess

    res = await db.execute(
        select(StrategySession).where(
            StrategySession.robot_plan_id == plan.id,
            StrategySession.status == "active",
        )
    )
    existing = res.scalar_one_or_none()
    if existing is not None:
        plan.session_id = existing.id
        return existing

    sess = StrategySession(
        id=new_uuid(),
        user_id=plan.user_id,
        robot_plan_id=plan.id,
        ticker=plan.ticker,
        status="active",
        entry_reason=entry_reason,
        plan_version=plan_version_hash(plan),
        override_log=[],
        started_at=_now(),
    )
    db.add(sess)
    await db.flush()
    plan.session_id = sess.id
    logger.info("strategy_session_opened", session_id=sess.id, plan_id=plan.id)
    return sess


async def append_session_event(
    db: AsyncSession,
    *,
    plan: RobotPlan,
    action: str,
    detail: dict[str, Any] | None = None,
    close_session: bool = False,
    actor: str | None = None,
) -> StrategySession | None:
    sess = await ensure_session(db, plan=plan, entry_reason=action)
    log = list(sess.override_log or [])
    log.append(
        {
            "action": action,
            "at": _now().isoformat(),
            "actor": actor or "robot",
            "detail": detail or {},
        }
    )
    sess.override_log = log[-200:]
    flag_modified(sess, "override_log")
    if close_session:
        sess.status = "closed"
        sess.ended_at = _now()
        pnl = 0.0
        if detail and detail.get("realized_pnl") is not None:
            pnl = float(detail["realized_pnl"])
        sess.total_pnl = float(sess.total_pnl or 0.0) + pnl
        logger.info("strategy_session_closed", session_id=sess.id, action=action)
    return sess


def session_to_dict(sess: StrategySession) -> dict[str, Any]:
    return {
        "id": sess.id,
        "user_id": sess.user_id,
        "robot_plan_id": sess.robot_plan_id,
        "ticker": sess.ticker,
        "status": sess.status,
        "entry_reason": sess.entry_reason,
        "plan_version": sess.plan_version,
        "override_log": sess.override_log or [],
        "total_pnl": sess.total_pnl,
        "total_fees": sess.total_fees,
        "total_funding": sess.total_funding,
        "started_at": sess.started_at.isoformat() if sess.started_at else None,
        "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
    }
