"""Email provider webhook endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status

from app.core.deps import get_db
from app.core.logging import get_logger
from app.services.email.webhooks import (
    parse_postmark_event,
    parse_sendgrid_events,
    record_email_event,
    verify_postmark_signature,
    verify_sendgrid_signature,
)
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/webhooks/email", tags=["email-webhooks"])
logger = get_logger(__name__)


@router.post("/sendgrid")
async def sendgrid_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    body = await request.body()
    signature = request.headers.get("X-Twilio-Email-Event-Webhook-Signature", "")
    timestamp = request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp", "")
    if not verify_sendgrid_signature(body, signature, timestamp):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid webhook signature")

    events = parse_sendgrid_events(body)
    for event in events:
        event_type = str(event.get("event", "unknown"))
        email = event.get("email")
        occurred = datetime.fromtimestamp(
            int(event.get("timestamp", 0)), tz=timezone.utc
        )
        await record_email_event(
            db,
            provider_message_id=event.get("sg_message_id"),
            event_type=event_type,
            occurred_at=occurred,
            raw_payload=event,
            recipient_email=email,
        )
    await db.commit()
    return {"ok": True, "processed": len(events)}


@router.post("/postmark")
async def postmark_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    body = await request.body()
    signature = request.headers.get("X-Postmark-Signature", "")
    if not verify_postmark_signature(body, signature):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid webhook signature")

    event = parse_postmark_event(body)
    record_type = str(event.get("RecordType", "unknown"))
    email = event.get("Email") or event.get("Recipient")
    occurred_raw = event.get("DeliveredAt") or event.get("BouncedAt") or event.get("ReceivedAt")
    occurred = datetime.now(timezone.utc)
    if occurred_raw:
        try:
            occurred = datetime.fromisoformat(str(occurred_raw).replace("Z", "+00:00"))
        except ValueError:
            pass

    await record_email_event(
        db,
        provider_message_id=str(event.get("MessageID", "")),
        event_type=record_type,
        occurred_at=occurred,
        raw_payload=event,
        recipient_email=email,
    )
    await db.commit()
    return {"ok": True}
