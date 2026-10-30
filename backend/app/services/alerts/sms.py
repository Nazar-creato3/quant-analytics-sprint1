"""SMS and voice via Twilio (or stub/sms.ru)."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings, get_settings

try:
    from app.core.logging import get_logger

    logger = get_logger(__name__)
except Exception:  # pragma: no cover — local checkout may have corrupted logging.py
    import logging

    logger = logging.getLogger(__name__)


async def send_sms(to: str, body: str, *, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    provider = (settings.SMS_PROVIDER or "stub").strip().lower()
    if provider == "stub":
        logger.info("sms_stub", to=to[-4:], body_preview=body[:120])
        return {"ok": True, "provider": "stub", "sid": "stub-sms"}
    if provider == "twilio":
        return await _twilio_sms(settings, to, body)
    if provider == "smsru":
        return await _smsru_send(settings, to, body)
    logger.warning("sms_unknown_provider", provider=provider)
    return {"ok": False, "error": f"unknown provider: {provider}"}


async def place_voice_call(
    to: str,
    message: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    provider = (settings.SMS_PROVIDER or "stub").strip().lower()
    if provider == "stub":
        logger.info("voice_stub", to=to[-4:], message_preview=message[:120])
        return {"ok": True, "provider": "stub", "sid": "stub-call"}
    if provider == "twilio":
        return await _twilio_voice(settings, to, message)
    logger.warning("voice_unsupported_provider", provider=provider)
    return {"ok": False, "error": f"voice not supported for provider: {provider}"}


async def _twilio_sms(settings: Settings, to: str, body: str) -> dict[str, Any]:
    if not settings.twilio_configured:
        return {"ok": False, "error": "twilio_not_configured"}
    url = f"https://api.auth.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    data = {
        "To": to,
        "From": settings.TWILIO_FROM_NUMBER,
        "Body": body[:1600],
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                url,
                data=data,
                auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            )
        payload = resp.json() if resp.content else {}
        ok = resp.status_code in (200, 201) and not payload.get("error_code")
        if ok:
            logger.info("twilio_sms_sent", sid=payload.get("sid"), to=to[-4:])
        else:
            logger.warning("twilio_sms_failed", status=resp.status_code, body=str(payload)[:300])
        return {"ok": ok, "provider": "twilio", "sid": payload.get("sid"), "detail": payload}
    except Exception as exc:
        logger.warning("twilio_sms_failed", error=str(exc)[:200])
        return {"ok": False, "error": str(exc)[:200]}


async def _twilio_voice(settings: Settings, to: str, message: str) -> dict[str, Any]:
    if not settings.twilio_configured:
        return {"ok": False, "error": "twilio_not_configured"}
    # TwiML Say — short, loud message for wake-up calls.
    safe = message.replace("&", "and").replace("<", "").replace(">", "")[:400]
    twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Say loop="2">{safe}</Say></Response>'
    url = f"https://api.auth.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Calls.json"
    data = {
        "To": to,
        "From": settings.TWILIO_FROM_NUMBER,
        "Twiml": twiml,
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                url,
                data=data,
                auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            )
        payload = resp.json() if resp.content else {}
        ok = resp.status_code in (200, 201) and not payload.get("error_code")
        if ok:
            logger.info("twilio_voice_sent", sid=payload.get("sid"), to=to[-4:])
        else:
            logger.warning("twilio_voice_failed", status=resp.status_code, body=str(payload)[:300])
        return {"ok": ok, "provider": "twilio", "sid": payload.get("sid"), "detail": payload}
    except Exception as exc:
        logger.warning("twilio_voice_failed", error=str(exc)[:200])
        return {"ok": False, "error": str(exc)[:200]}


async def _smsru_send(settings: Settings, to: str, body: str) -> dict[str, Any]:
    api_key = (settings.SMSRU_API_KEY or "").strip()
    if not api_key:
        return {"ok": False, "error": "smsru_not_configured"}
    params = urlencode({"api_id": api_key, "to": to, "msg": body[:800], "json": "1"})
    url = f"https://sms.ru/sms/send?{params}"
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(url)
        payload = resp.json() if resp.content else {}
        ok = payload.get("status") == "OK"
        return {"ok": ok, "provider": "smsru", "detail": payload}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}
