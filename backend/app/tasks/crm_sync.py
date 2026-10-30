"""Celery task: async Twenty CRM sync with retry + audit."""
from __future__ import annotations

from app.core.logging import get_logger
from app.services.crm.twenty import TwentyCrmError
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)

_MAX_RETRIES = 5
_RETRY_BASE_SECONDS = 60


@celery_app.task(
    bind=True,
    name="crm.sync_application_to_twenty",
    max_retries=_MAX_RETRIES,
    autoretry_for=(),
)
def sync_application_to_twenty_task(self, application_id: str, event: str) -> dict:
    try:
        return run_async(_sync_application(application_id, event))
    except TwentyCrmError as exc:
        if exc.retryable and self.request.retries < _MAX_RETRIES:
            countdown = _RETRY_BASE_SECONDS * (2 ** self.request.retries)
            logger.warning(
                "Twenty CRM sync retry scheduled",
                application_id=application_id,
                sync_event=event,
                retry=self.request.retries + 1,
                countdown=countdown,
                error=str(exc),
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        raise


async def _sync_application(application_id: str, event: str) -> dict:
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.services.crm.sync import sync_application_to_twenty
    from app.domain.application_flow import ApplicationORM

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ApplicationORM).where(ApplicationORM.id == application_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            logger.warning("CRM sync skipped — application not found", application_id=application_id)
            return {"ok": False, "reason": "not_found"}

        outcome = await sync_application_to_twenty(db, app, event=event)
        await db.commit()
        return outcome
