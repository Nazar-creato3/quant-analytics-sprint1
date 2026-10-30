"""Celery task: process email jobs with retry and failover."""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.logging import get_logger
from app.domain.email_transactional import EmailJobORM
from app.services.email.pipeline import mark_job_dead_letter
from app.services.email.providers import EmailProviderError, send_with_failover
from app.services.email.template_renderer import render_template
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)

_MAX_RETRIES = 5
_RETRY_BASE_SECONDS = 30


@celery_app.task(
    bind=True,
    name="email.send_job",
    max_retries=_MAX_RETRIES,
    autoretry_for=(),
)
def send_email_job_task(self, job_id: str) -> dict:
    try:
        return run_async(_process_job(job_id))
    except EmailProviderError as exc:
        if exc.retryable and self.request.retries < _MAX_RETRIES:
            countdown = _RETRY_BASE_SECONDS * (2 ** self.request.retries)
            logger.warning(
                "Email job retry scheduled",
                job_id=job_id,
                retry=self.request.retries + 1,
                countdown=countdown,
                error=str(exc),
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        run_async(_dead_letter(job_id, str(exc)))
        raise


async def _dead_letter(job_id: str, error: str) -> None:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        job = await db.get(EmailJobORM, job_id)
        if job:
            await mark_job_dead_letter(db, job, error)
            await db.commit()


async def _process_job(job_id: str) -> dict:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        job = await db.get(EmailJobORM, job_id)
        if not job:
            return {"ok": False, "reason": "not_found"}
        if job.status in ("sent", "dead_letter"):
            return {"ok": True, "reason": "already_final"}

        job.status = "processing"
        job.attempts += 1
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()

        rendered = await render_template(db, job.template, job.payload)
        try:
            result = await send_with_failover(
                to_email=job.to_email,
                subject=rendered.subject,
                html_body=rendered.html_body,
                text_body=rendered.text_body,
                idempotency_key=job.idempotency_key,
            )
        except EmailProviderError:
            job.status = "pending"
            await db.commit()
            raise

        job.status = "sent"
        job.provider = result.provider
        job.provider_message_id = result.message_id
        job.sent_at = datetime.now(timezone.utc)
        job.updated_at = job.sent_at
        await db.commit()

        logger.info(
            "Email job completed",
            job_id=job.id,
            job_type=job.job_type,
            template=job.template,
            provider=result.provider,
            status="sent",
            latency_ms=round(result.latency_ms, 2),
        )
        return {"ok": True, "job_id": job.id, "provider": result.provider}
