"""Phone OTP via Twilio or SMS.ru abstraction."""
from __future__ import annotations

import hashlib
import secrets

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.utils.cache import cache_get, cache_set

logger = get_logger(__name__)

OTP_TTL_SECONDS = 600


def _otp_cache_key(phone_hash: str) -> str:
    return f"phone_otp:{phone_hash}"


def hash_otp(phone_hash: str, code: str) -> str:
    material = f"{phone_hash}:{code}:{settings.SECRET_KEY}"
    return hashlib.sha256(material.encode()).hexdigest()


async def send_phone_otp(phone: str, phone_hash: str) -> str:
    """Generate OTP, store hash in Redis, dispatch via configured SMS provider."""
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    await cache_set(_otp_cache_key(phone_hash), hash_otp(phone_hash, code), OTP_TTL_SECONDS)

    provider = (settings.SMS_PROVIDER or "stub").lower()
    if provider == "twilio":
        await _send_twilio(phone, code)
    elif provider == "smsru":
        await _send_smsru(phone, code)
    else:
        logger.info("OTP stub dispatch", phone_last4=phone[-4:], code=code if settings.is_development else "****")
    return code if settings.is_development else ""


async def verify_phone_otp(phone_hash: str, code: str) -> bool:
    stored = await cache_get(_otp_cache_key(phone_hash))
    if not stored:
        return False
    return stored == hash_otp(phone_hash, code.strip())


async def _send_twilio(phone: str, code: str) -> None:
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise RuntimeError("Twilio credentials not configured")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(
            url,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            data={
                "From": settings.TWILIO_FROM_NUMBER,
                "To": phone,
                "Body": f"Your Apex Intel verification code: {code}",
            },
        )


async def _send_smsru(phone: str, code: str) -> None:
    if not settings.SMSRU_API_KEY:
        raise RuntimeError("SMS.ru API key not configured")
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.get(
            "https://sms.ru/sms/send",
            params={
                "api_id": settings.SMSRU_API_KEY,
                "to": phone,
                "msg": f"Код подтверждения Apex Intel: {code}",
                "json": 1,
            },
        )
