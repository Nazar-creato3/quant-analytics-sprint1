"""Repository helpers for position audit trigger and trade selection."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Maneuver, ManeuverStatus, PositionAudit
from app.services.audit.types import ClosedTradeRecord, maneuver_to_trade_record
from app.services.portfolio.user_scope import maneuvers_for_user

# Trigger as soon as one closed trade exists since the last audit.
AUDIT_BATCH_SIZE = 1
# How many pending closes to include in one report (not the trigger).
AUDIT_REPORT_LIMIT = 500
# Backward-compatible alias used across API, tasks, and tests.
AUDIT_THRESHOLD = AUDIT_BATCH_SIZE


def expiration_closes_since_audit_stmt(
    user_id: str,
    watermark: datetime | None,
) -> Select:
    """All closed maneuvers since the last audit watermark — never LIMIT."""
    stmt = maneuvers_for_user(user_id).where(
        Maneuver.status == ManeuverStatus.CLOSED,
    )
    if watermark is not None:
        stmt = stmt.where(Maneuver.closed_at > watermark)
    return stmt


async def last_completed_audit(db: AsyncSession, user_id: str) -> PositionAudit | None:
    result = await db.execute(
        select(PositionAudit)
        .where(PositionAudit.user_id == user_id, PositionAudit.status == "complete")
        .order_by(desc(PositionAudit.completed_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def count_expiration_closes_since_last_audit(
    db: AsyncSession,
    user_id: str,
) -> tuple[int, datetime | None]:
    """Count closed trades since the last completed audit."""
    last = await last_completed_audit(db, user_id)
    watermark = last.completed_at if last and last.completed_at else None

    stmt = expiration_closes_since_audit_stmt(user_id, watermark)
    result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    count = int(result.scalar_one() or 0)
    return count, watermark


async def fetch_audit_trades(
    db: AsyncSession,
    user_id: str,
    *,
    limit: int = AUDIT_REPORT_LIMIT,
) -> list[ClosedTradeRecord]:
    """Fetch the most recent N closed trades for one audit run."""
    last = await last_completed_audit(db, user_id)
    watermark = last.completed_at if last and last.completed_at else None

    stmt = (
        expiration_closes_since_audit_stmt(user_id, watermark)
        .order_by(desc(Maneuver.closed_at))
        .limit(limit)
    )

    result = await db.execute(stmt)
    maneuvers = list(result.scalars().all())
    records: list[ClosedTradeRecord] = []
    for m in maneuvers:
        rec = maneuver_to_trade_record(m)
        if rec is not None:
            records.append(rec)
    return records


async def create_audit_run(db: AsyncSession, user_id: str, trade_count: int) -> PositionAudit:
    audit = PositionAudit(
        user_id=user_id,
        status="pending",
        trade_count=trade_count,
        required_count=AUDIT_BATCH_SIZE,
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    await db.flush()
    return audit


def audit_ready(count: int) -> bool:
    """True when at least one closed trade is waiting since the last audit."""
    return count >= AUDIT_BATCH_SIZE


async def try_enqueue_position_audit(
    db: AsyncSession,
    user_id: str,
) -> PositionAudit | None:
    """Create a pending audit row when the user reached AUDIT_BATCH_SIZE closes.

    Returns the new audit or None if below threshold / audit already running.
    Does not commit or enqueue Celery — caller handles that.
    """
    if await has_running_audit(db, user_id):
        return None
    count, _ = await count_expiration_closes_since_last_audit(db, user_id)
    if not audit_ready(count):
        return None
    return await create_audit_run(db, user_id, count)


async def has_running_audit(db: AsyncSession, user_id: str) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(PositionAudit)
        .where(
            PositionAudit.user_id == user_id,
            PositionAudit.status.in_(("pending", "running")),
        )
    )
    return int(result.scalar_one() or 0) > 0
