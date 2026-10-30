"""Async email job pipeline — enqueue, idempotency, suppression checks."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import new_uuid
from app.domain.email_transactional import EmailJobORM, SuppressedEmailORM
from app.utils.cache import cache_exists, cache_set

logger = get_logger(__name__)

IDEMPOTENCY_TTL_SECONDS = 86400  # 24h


def build_idempotency_key(job_type: str, user_id: str | None, entity_id: str | None = None) -> str:
    material = f"{job_type}:{user_id or 'anon'}:{entity_id or 'none'}"
    return hashlib.sha256(material.encode()).hexdigest()


async def is_email_suppressed(db: AsyncSession, email: str) -> bool:
    result = await db.execute(
        select(SuppressedEmailORM).where(
            SuppressedEmailORM.email == email.lower(),
            SuppressedEmailORM.cleared_at.is_(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def enqueue_email_job(
    db: AsyncSession,
    *,
    job_type: str,
    template: str,
    to_email: str,
    payload: dict,
    user_id: str | None = None,
    entity_id: str | None = None,
) -> EmailJobORM | None:
    """
    Create email job and dispatch to Celery. Returns None if duplicate/suppressed.
    """
    email = to_email.lower().strip()
    if await is_email_suppressed(db, email):
        logger.info("Email suppressed, skipping job", to_email=email, job_type=job_type)
        return None

    idempotency_key = build_idempotency_key(job_type, user_id, entity_id)
    redis_key = f"email:idempotency:{idempotency_key}"
    if await cache_exists(redis_key):
        logger.info("Duplicate email job skipped", idempotency_key=idempotency_key)
        return None

    existing = await db.execute(
        select(EmailJobORM).where(
            EmailJobORM.idempotency_key == idempotency_key,
            EmailJobORM.status.in_(("pending", "processing", "sent")),
        )
    )
    if existing.scalar_one_or_none():
        await cache_set(redis_key, {"ok": True}, IDEMPOTENCY_TTL_SECONDS)
        return None

    job = EmailJobORM(
        id=new_uuid(),
        job_type=job_type,
        template=template,
        to_email=email,
        payload=payload,
        status="pending",
        idempotency_key=idempotency_key,
        attempts=0,
    )
    db.add(job)
    await db.flush()
    await cache_set(redis_key, {"job_id": job.id}, IDEMPOTENCY_TTL_SECONDS)

    schedule_email_send(job.id)
    logger.info(
        "Email job enqueued",
        job_id=job.id,
        job_type=job_type,
        template=template,
        to_email=email,
        idempotency_key=idempotency_key,
    )
    return job


def schedule_email_send(job_id: str) -> None:
    """Enqueue Celery task (no-op if broker unavailable in dev)."""
    from app.core.config import settings

    if settings.QA_E2E_DEMO:
        return
    try:
        from app.tasks.email import send_email_job_task

        send_email_job_task.delay(job_id)
    except Exception as exc:
        logger.warning("Celery email dispatch unavailable", job_id=job_id, error=str(exc))


async def mark_job_dead_letter(db: AsyncSession, job: EmailJobORM, error: str) -> None:
    job.status = "dead_letter"
    job.last_error = error[:2000]
    job.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.error(
        "Email job moved to dead letter queue",
        job_id=job.id,
        job_type=job.job_type,
        template=job.template,
        attempts=job.attempts,
        error=error[:500],
    )
    try:
        from app.core.config import settings
        from app.services.alerts.telegram import send_telegram_message

        if settings.telegram_configured:
            await send_telegram_message(
                settings.TELEGRAM_CHAT_ID,
                f"Email DLQ: job {job.id} ({job.job_type}/{job.template}) failed after {job.attempts} attempts",
            )
    except Exception:
        pass
