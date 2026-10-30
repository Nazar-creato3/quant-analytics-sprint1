"""Celery tasks for access policy (trial expiration)."""
from __future__ import annotations

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="access_policy.expire_trials_task")
def expire_trials_task() -> dict:
    return run_async(_expire_trials())


async def _expire_trials() -> dict:
    from app.db.session import AsyncSessionLocal
    from app.services.access_policy.service import access_policy_service

    async with AsyncSessionLocal() as db:
        count = await access_policy_service.expire_due_trials(db)
        await db.commit()
    logger.info("Trial expiration job finished", expired=count)
    return {"expired": count}
