"""Enqueue position audits after expiration closes without importing Celery at module load."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.audit.repository import try_enqueue_position_audit

logger = get_logger(__name__)


async def enqueue_position_audits_for_users(
    db: AsyncSession,
    user_ids: set[str],
) -> list[str]:
    """Auto-trigger audit after every new expiration close."""
    if not user_ids:
        return []

    audit_ids: list[str] = []
    for user_id in sorted(user_ids):
        audit = await try_enqueue_position_audit(db, user_id)
        if audit is None:
            continue
        audit_ids.append(audit.id)
        logger.info(
            "position_audit_auto_enqueued",
            audit_id=audit.id,
            user_id=user_id,
            trade_count=audit.trade_count,
        )

    if audit_ids:
        await db.commit()
        from app.tasks.position_audit import run_position_audit_task

        for audit_id in audit_ids:
            run_position_audit_task.delay(audit_id)

    return audit_ids
