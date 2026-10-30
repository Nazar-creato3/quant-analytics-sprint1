"""Email-confirmed password change (OTP + optional magic link)."""
from __future__ import annotations

import hashlib
import secrets

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.services.application.email_verification import send_password_change_email
from app.utils.cache import cache_delete, cache_get, cache_set

logger = get_logger(__name__)

PASSWORD_CHANGE_TTL_SECONDS = 900  # 15 minutes


def _cache_key(user_id: str) -> str:
    return f"pwd_change:{user_id}"


def _hash_otp(user_id: str, code: str) -> str:
    material = f"{user_id}:{code}:{settings.SECRET_KEY}"
    return hashlib.sha256(material.encode()).hexdigest()


def _hash_new_password(user_id: str, new_password: str) -> str:
    material = f"{user_id}:new:{new_password}:{settings.SECRET_KEY}"
    return hashlib.sha256(material.encode()).hexdigest()


def smtp_configured() -> bool:
    return bool(settings.SMTP_HOST.strip() and settings.SMTP_USER.strip())


def email_delivery_configured() -> bool:
    if smtp_configured():
        return True
    if settings.UNISENDER_API_KEY.strip():
        return True
    provider = settings.EMAIL_PRIMARY_PROVIDER.lower()
    if provider == "sendgrid" and settings.SENDGRID_API_KEY.strip():
        return True
    if provider == "postmark" and settings.POSTMARK_SERVER_TOKEN.strip():
        return True
    if provider == "ses" and settings.AWS_ACCESS_KEY_ID.strip() and settings.AWS_SES_REGION.strip():
        return True
    return False


async def request_password_change(user_id: str, email: str, new_password: str) -> str:
    """Generate OTP, store pending change in Redis, send confirmation email."""
    if not email_delivery_configured() and not settings.is_development:
        raise RuntimeError(
            "Email delivery is not configured. Contact support or try again later."
        )

    code = f"{secrets.randbelow(900000) + 100000:06d}"
    token = secrets.token_urlsafe(32)
    payload = {
        "otp_hash": _hash_otp(user_id, code),
        "new_password_hash": _hash_new_password(user_id, new_password),
        "token": token,
    }
    await cache_set(_cache_key(user_id), payload, PASSWORD_CHANGE_TTL_SECONDS)
    await send_password_change_email(email, code=code, magic_token=token)
    logger.info("Password change requested", user_id=user_id, email=email)
    return code if settings.is_development else ""


async def confirm_password_change(
    user_id: str,
    *,
    code: str | None = None,
    token: str | None = None,
    new_password: str,
) -> bool:
    """Verify OTP or magic token and return Argon2id hash for the new password."""
    stored = await cache_get(_cache_key(user_id))
    if not stored or not isinstance(stored, dict):
        return False

    expected_new_hash = stored.get("new_password_hash")
    if not expected_new_hash or expected_new_hash != _hash_new_password(user_id, new_password):
        return False

    attempts = int(stored.get("attempts") or 0)
    verified = False
    if code:
        otp_hash = stored.get("otp_hash")
        verified = bool(otp_hash and otp_hash == _hash_otp(user_id, code.strip()))
    elif token:
        stored_token = stored.get("token") or ""
        presented = (token or "").strip()
        verified = bool(stored_token and presented and secrets.compare_digest(stored_token, presented))

    if not verified:
        attempts += 1
        if attempts >= 5:
            await cache_delete(_cache_key(user_id))
            return False
        stored["attempts"] = attempts
        await cache_set(_cache_key(user_id), stored, PASSWORD_CHANGE_TTL_SECONDS)
        return False

    await cache_delete(_cache_key(user_id))
    return True


def apply_new_password_hash(new_password: str) -> str:
    return hash_password(new_password)
