"""Celery tasks for position audit pipeline."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.position_audit.run_position_audit_task")
def run_position_audit_task(audit_id: str) -> dict[str, Any]:
    return run_async(_async_run_audit(audit_id))


async def _async_run_audit(audit_id: str) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.audit.pipeline import run_position_audit

    async with AsyncSessionLocal() as session:
        return await run_position_audit(session, audit_id)


@celery_app.task(name="app.tasks.position_audit.check_audit_triggers_task")
def check_audit_triggers_task() -> dict[str, Any]:
    return run_async(_async_check_triggers())


@celery_app.task(name="app.tasks.position_audit.scan_barrier_closes_task")
def scan_barrier_closes_task() -> dict[str, Any]:
    """Fast paper SL/TP scan (~15s) independent of the slower audit trigger."""
    return run_async(_async_scan_barriers())


async def _async_scan_barriers() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.portfolio.barrier_close import close_barrier_hits

    async with AsyncSessionLocal() as session:
        return await close_barrier_hits(session)


async def _async_check_triggers() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.portfolio.audit_trigger import enqueue_position_audits_for_users
    from app.services.portfolio.expiration_close import (
        close_expired_positions,
        users_with_expiration_closes_pending_audit,
    )

    triggered: list[str] = []
    async with AsyncSessionLocal() as session:
        from app.services.portfolio.barrier_close import close_barrier_hits

        barriers = await close_barrier_hits(session)
        await close_expired_positions(session)
        user_ids = await users_with_expiration_closes_pending_audit(session)
        triggered = await enqueue_position_audits_for_users(session, set(user_ids))

    return {"triggered": triggered, "count": len(triggered), "barriers": barriers}
