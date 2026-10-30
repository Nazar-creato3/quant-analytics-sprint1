"""Orchestrate application → Twenty CRM sync (DB + audit)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.application_flow import ApplicationORM
from app.services.crm.twenty import (
    CrmSyncStatus,
    TwentyCrmClient,
    TwentyCrmError,
    twenty_crm_client,
)
from app.utils.audit import AuditAction, audit
from app.utils.helpers import utcnow

logger = get_logger(__name__)


def schedule_application_crm_sync(application_id: str, event: str) -> None:
    """Enqueue async CRM sync (no-op if Celery unavailable in dev)."""
    try:
        from app.tasks.crm_sync import sync_application_to_twenty_task

        sync_application_to_twenty_task.delay(application_id, event)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "CRM sync enqueue failed — will require manual retry",
            application_id=application_id,
            sync_event=event,
            error=str(exc),
        )


async def sync_application_to_twenty(
    db: AsyncSession,
    app: ApplicationORM,
    *,
    event: str,
    client: TwentyCrmClient | None = None,
) -> dict:
    crm = client or twenty_crm_client

    if not crm.configured:
        app.crm_sync_status = CrmSyncStatus.SKIPPED.value
        app.crm_last_sync_at = utcnow()
        await db.flush()
        await audit.log(
            db,
            action=AuditAction.CRM_SYNC_SKIPPED,
            resource_type="application",
            resource_id=app.id,
            details={"event": event, "reason": "twenty_not_configured"},
            success=True,
        )
        return {"ok": True, "skipped": True}

    try:
        result = await crm.sync_application(app, event=event)
        if result.get("skipped"):
            app.crm_sync_status = CrmSyncStatus.SKIPPED.value
        else:
            app.twenty_crm_id = result.get("person_id") or app.twenty_crm_id
            company_id = result.get("company_id")
            if company_id:
                app.twenty_company_id = company_id
            app.crm_sync_status = CrmSyncStatus.SYNCED.value
        app.crm_last_sync_at = utcnow()
        app.updated_at = datetime.now(timezone.utc)
        await db.flush()

        await audit.log(
            db,
            action=AuditAction.CRM_SYNC_SUCCESS,
            resource_type="application",
            resource_id=app.id,
            details={
                "event": event,
                "twenty_crm_id": app.twenty_crm_id,
                "twenty_company_id": app.twenty_company_id,
                "status": app.status,
            },
            success=True,
        )
        return {"ok": True, "twenty_crm_id": app.twenty_crm_id}

    except TwentyCrmError as exc:
        app.crm_sync_status = CrmSyncStatus.FAILED.value
        app.crm_last_sync_at = utcnow()
        await db.flush()

        await audit.log(
            db,
            action=AuditAction.CRM_SYNC_FAILED,
            resource_type="application",
            resource_id=app.id,
            details={"event": event, "status": app.status},
            success=False,
            error=str(exc),
        )
        logger.error(
            "Twenty CRM sync failed",
            application_id=app.id,
            sync_event=event,
            error=str(exc),
            retryable=exc.retryable,
        )
        raise
