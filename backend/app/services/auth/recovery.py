"""Account recovery (forgot password) with enumeration resistance."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password, revoke_all_refresh_families
from app.db.models import User, new_uuid
from app.domain.email_transactional import RecoveryTokenORM
from app.services.auth.security_audit import write_security_audit
from app.services.email.pipeline import enqueue_email_job
from app.services.email.tokens import (
    RECOVERY_TTL_MINUTES,
    generate_raw_token,
    hash_token,
    is_expired,
    recovery_expires_at,
    verify_token_hash,
)
from app.utils.cache import cache_delete, cache_get, cache_set, rate_limit_check

logger = get_logger(__name__)

GENERIC_RESPONSE = {
    "ok": True,
    "message": "If an account exists for this email, password reset instructions have been sent.",
}

# Target minimum response time to resist timing enumeration (ms).
_MIN_RESPONSE_MS = 250

ABUSE_WINDOW_SECONDS = 3600
ABUSE_THRESHOLD = 5
WASNT_ME_TOKEN_TTL_SECONDS = 86400


async def _pad_response_time(started: float) -> None:
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms < _MIN_RESPONSE_MS:
        await asyncio.sleep((_MIN_RESPONSE_MS - elapsed_ms) / 1000)


async def _check_abuse_alert(db: AsyncSession, user_id: str, email: str) -> None:
    key = f"recovery:abuse:{user_id}"
    count_raw = await cache_get(key)
    count = int(count_raw.get("count", 0) if isinstance(count_raw, dict) else 0) + 1
    await cache_set(key, {"count": count}, ABUSE_WINDOW_SECONDS)
    if count >= ABUSE_THRESHOLD:
        await write_security_audit(
            db,
            event_type="recovery_abuse_alert",
            user_id=user_id,
            details={"email": email, "count": count, "window_seconds": ABUSE_WINDOW_SECONDS},
        )
        logger.warning("Recovery abuse alert", user_id=user_id, email=email, count=count)


async def _invalidate_prior_tokens(db: AsyncSession, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(RecoveryTokenORM)
        .where(RecoveryTokenORM.user_id == user_id, RecoveryTokenORM.used_at.is_(None))
        .values(used_at=now)
    )


def build_recovery_url(raw_token: str) -> str:
    base = settings.EMAIL_VERIFICATION_BASE_URL.rstrip("/")
    return f"{base}/reset?token={raw_token}"


def build_wasnt_me_url(raw_token: str) -> str:
    base = settings.EMAIL_VERIFICATION_BASE_URL.rstrip("/")
    return f"{base}/wasnt-me?token={raw_token}"


async def issue_wasnt_me_token(user_id: str) -> str:
    raw = generate_raw_token()
    await cache_set(
        f"wasnt_me:{hash_token(raw)}",
        {"user_id": user_id},
        WASNT_ME_TOKEN_TTL_SECONDS,
    )
    return raw


async def _alert_suspicious_recovery_attempt(
    db: AsyncSession,
    *,
    user_id: str | None,
    reason: str,
    ip: str | None,
) -> None:
    await write_security_audit(
        db,
        event_type="recovery_token_suspicious",
        user_id=user_id,
        ip=ip,
        details={"reason": reason},
    )
    if settings.telegram_configured:
        try:
            from app.services.alerts.telegram import send_telegram_message

            await send_telegram_message(
                settings.TELEGRAM_CHAT_ID,
                f"⚠️ Suspicious password-reset token use ({reason}) "
                f"user={user_id or 'unknown'} ip={ip or 'unknown'}",
                settings=settings,
            )
        except Exception as exc:
            logger.warning("Telegram security alert failed", error=str(exc))


async def request_password_recovery(
    db: AsyncSession,
    *,
    email: str,
    ip: str | None,
    user_agent: str | None,
) -> dict:
    started = time.perf_counter()
    normalized = email.lower().strip()

    allowed_ip, _ = await rate_limit_check(
        f"recover:ip:{ip or 'unknown'}",
        settings.RECOVERY_RATE_LIMIT_PER_IP,
        settings.RECOVERY_RATE_LIMIT_WINDOW_SECONDS,
        fail_closed=True,
    )
    allowed_email, _ = await rate_limit_check(
        f"recover:email:{normalized}",
        settings.RECOVERY_RATE_LIMIT_PER_EMAIL,
        settings.RECOVERY_RATE_LIMIT_WINDOW_SECONDS,
        fail_closed=True,
    )
    if not allowed_ip or not allowed_email:
        await _pad_response_time(started)
        return GENERIC_RESPONSE

    result = await db.execute(select(User).where(User.email == normalized))
    user = result.scalar_one_or_none()

    if user and user.is_active:
        raw_token = generate_raw_token()
        token_hash = hash_token(raw_token)
        await _invalidate_prior_tokens(db, user.id)
        token_row = RecoveryTokenORM(
            id=new_uuid(),
            user_id=user.id,
            token_hash=token_hash,
            expires_at=recovery_expires_at(),
        )
        db.add(token_row)
        await db.flush()

        await enqueue_email_job(
            db,
            job_type="password_recovery",
            template="password_recovery",
            to_email=user.email,
            payload={
                "name": user.email.split("@")[0],
                "reset_url": build_recovery_url(raw_token),
                "ttl_minutes": RECOVERY_TTL_MINUTES,
            },
            user_id=user.id,
            entity_id=token_row.id,
        )
        await write_security_audit(
            db,
            event_type="recovery_requested",
            user_id=user.id,
            ip=ip,
            user_agent=user_agent,
        )
        await _check_abuse_alert(db, user.id, user.email)

    await _pad_response_time(started)
    return GENERIC_RESPONSE


async def reset_password_with_token(
    db: AsyncSession,
    *,
    raw_token: str,
    new_password: str,
    ip: str | None,
    user_agent: str | None,
) -> bool:
    token_hash = hash_token(raw_token.strip())
    result = await db.execute(
        select(RecoveryTokenORM).where(RecoveryTokenORM.token_hash == token_hash)
    )
    token_row = result.scalar_one_or_none()
    if not token_row:
        await _alert_suspicious_recovery_attempt(db, user_id=None, reason="unknown_token", ip=ip)
        return False

    if not verify_token_hash(raw_token.strip(), token_row.token_hash):
        await _alert_suspicious_recovery_attempt(
            db,
            user_id=token_row.user_id,
            reason="hash_mismatch",
            ip=ip,
        )
        return False
    if token_row.used_at is not None:
        await _alert_suspicious_recovery_attempt(
            db,
            user_id=token_row.user_id,
            reason="already_used",
            ip=ip,
        )
        return False
    if is_expired(token_row.expires_at):
        await _alert_suspicious_recovery_attempt(
            db,
            user_id=token_row.user_id,
            reason="expired",
            ip=ip,
        )
        return False

    user = await db.get(User, token_row.user_id)
    if not user or not user.is_active:
        return False

    now = datetime.now(timezone.utc)
    token_row.used_at = now
    user.hashed_password = hash_password(new_password)
    user.must_change_password = False
    await revoke_all_refresh_families(db, user.email)

    await write_security_audit(
        db,
        event_type="recovery_token_consumed",
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
        details={"token_id": token_row.id},
    )
    await write_security_audit(
        db,
        event_type="password_changed",
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
        details={"via": "recovery"},
    )
    await write_security_audit(
        db,
        event_type="sessions_revoked",
        user_id=user.id,
        ip=ip,
        details={"reason": "password_reset"},
    )

    await enqueue_email_job(
        db,
        job_type="password_changed",
        template="password_changed",
        to_email=user.email,
        payload={
            "changed_at": now.isoformat(),
            "ip": ip,
            "user_agent": user_agent,
            "wasnt_me_url": build_wasnt_me_url(await issue_wasnt_me_token(user.id)),
        },
        user_id=user.id,
        entity_id=token_row.id,
    )
    return True


async def report_unauthorized_password_change(
    db: AsyncSession,
    *,
    raw_token: str,
    ip: str | None,
    user_agent: str | None,
) -> bool:
    """Consume one-time 'this wasn't me' link — revoke sessions and flag for review."""
    cache_key = f"wasnt_me:{hash_token(raw_token.strip())}"
    cached = await cache_get(cache_key)
    if not isinstance(cached, dict):
        return False

    user_id = cached.get("user_id")
    if not user_id:
        return False

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        return False

    await revoke_all_refresh_families(db, user.email)
    await cache_delete(cache_key)

    await write_security_audit(
        db,
        event_type="account_flagged_for_review",
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
        details={"via": "wasnt_me_link"},
    )
    await write_security_audit(
        db,
        event_type="sessions_revoked",
        user_id=user.id,
        ip=ip,
        details={"reason": "wasnt_me_report"},
    )

    if settings.telegram_configured:
        try:
            from app.services.alerts.telegram import send_telegram_message

            await send_telegram_message(
                settings.TELEGRAM_CHAT_ID,
                f"🚨 User reported unauthorized password change: {user.email} ip={ip or 'unknown'}",
                settings=settings,
            )
        except Exception as exc:
            logger.warning("Telegram wasnt-me alert failed", error=str(exc))

    return True
