"""Provider webhook signature verification and event persistence."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import new_uuid
from app.domain.email_transactional import EmailEventORM, EmailJobORM, SuppressedEmailORM

logger = get_logger(__name__)

HARD_BOUNCE_EVENTS = frozenset({"bounce", "hard_bounce", "Bounce", "HardBounce"})
COMPLAINT_EVENTS = frozenset({"spamreport", "complaint", "SpamComplaint", "Complaint"})


def verify_sendgrid_signature(payload: bytes, signature: str, timestamp: str) -> bool:
    secret = settings.SENDGRID_WEBHOOK_SECRET
    if not secret:
        return False
    signed = f"{timestamp}{payload.decode('utf-8')}".encode()
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    try:
        return hmac.compare_digest(base64.b64encode(expected).decode(), signature)
    except Exception:
        return False


def verify_postmark_signature(payload: bytes, signature: str) -> bool:
    secret = settings.POSTMARK_WEBHOOK_SECRET
    if not secret:
        return False
    expected = base64.b64encode(
        hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


async def suppress_email(db: AsyncSession, email: str, reason: str) -> None:
    row = await db.get(SuppressedEmailORM, email.lower())
    if row and row.cleared_at is None:
        return
    if row:
        row.reason = reason
        row.suppressed_at = datetime.now(timezone.utc)
        row.cleared_at = None
    else:
        db.add(
            SuppressedEmailORM(
                email=email.lower(),
                reason=reason,
                suppressed_at=datetime.now(timezone.utc),
            )
        )


async def record_email_event(
    db: AsyncSession,
    *,
    provider_message_id: str | None,
    event_type: str,
    occurred_at: datetime,
    raw_payload: dict,
    recipient_email: str | None = None,
) -> EmailEventORM:
    job_id = None
    if provider_message_id:
        result = await db.execute(
            select(EmailJobORM).where(EmailJobORM.provider_message_id == provider_message_id).limit(1)
        )
        job = result.scalar_one_or_none()
        if job:
            job_id = job.id

    event = EmailEventORM(
        id=new_uuid(),
        job_id=job_id,
        provider_message_id=provider_message_id,
        event_type=event_type,
        occurred_at=occurred_at,
        raw_payload=raw_payload,
    )
    db.add(event)

    normalized = event_type.lower()
    if recipient_email and (
        normalized in {e.lower() for e in HARD_BOUNCE_EVENTS}
        or normalized in {e.lower() for e in COMPLAINT_EVENTS}
    ):
        reason = "hard_bounce" if "bounce" in normalized else "complaint"
        await suppress_email(db, recipient_email, reason)
        logger.warning("Email address suppressed", email=recipient_email, reason=reason)

    return event


def parse_sendgrid_events(body: bytes) -> list[dict]:
    return json.loads(body)


def parse_postmark_event(body: bytes) -> dict:
    return json.loads(body)
