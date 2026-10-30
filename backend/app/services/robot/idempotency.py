"""Idempotent robot level fills — unique (plan, level, action, celery_task_id)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import new_uuid
from app.db.robot_models import RobotLevelFill

logger = get_logger(__name__)


@dataclass
class FillClaim:
    claimed: bool
    fill: RobotLevelFill | None
    idempotency_key: str


def make_client_order_id(
    *,
    plan_id: str,
    level_id: str,
    action: str,
    stamp: str | None = None,
) -> str:
    ts = stamp or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{plan_id}_{level_id}_{action}_{ts}"[:120]


async def claim_level_fill(
    db: AsyncSession,
    *,
    plan_id: str,
    level_id: str,
    action: str,
    celery_task_id: str = "",
    qty: float = 0.0,
    price: float = 0.0,
    fee_usd: float = 0.0,
    liquidity: str = "taker",
    maneuver_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> FillClaim:
    """Insert fill row; on unique violation return existing (duplicate skip)."""
    task = celery_task_id or ""
    key = f"{plan_id}:{level_id}:{action}:{task}"

    # Fast path: already exists
    existing = await db.execute(
        select(RobotLevelFill).where(
            RobotLevelFill.plan_id == plan_id,
            RobotLevelFill.level_id == level_id,
            RobotLevelFill.action == action,
            RobotLevelFill.celery_task_id == task,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        logger.warning("robot_fill_duplicate", idempotency_key=key, fill_id=row.id)
        return FillClaim(claimed=False, fill=row, idempotency_key=key)

    fill = RobotLevelFill(
        id=new_uuid(),
        plan_id=plan_id,
        level_id=level_id,
        action=action,
        celery_task_id=task,
        client_order_id=make_client_order_id(
            plan_id=plan_id, level_id=level_id, action=action
        ),
        qty=float(qty),
        price=float(price),
        fee_usd=float(fee_usd),
        liquidity=liquidity if liquidity in {"maker", "taker"} else "taker",
        maneuver_id=maneuver_id,
        meta=meta or {},
    )
    try:
        async with db.begin_nested():
            db.add(fill)
            await db.flush()
    except IntegrityError:
        existing2 = await db.execute(
            select(RobotLevelFill).where(
                RobotLevelFill.plan_id == plan_id,
                RobotLevelFill.level_id == level_id,
                RobotLevelFill.action == action,
                RobotLevelFill.celery_task_id == task,
            )
        )
        row2 = existing2.scalar_one_or_none()
        logger.warning("robot_fill_unique_violation", idempotency_key=key)
        return FillClaim(claimed=False, fill=row2, idempotency_key=key)

    return FillClaim(claimed=True, fill=fill, idempotency_key=key)
