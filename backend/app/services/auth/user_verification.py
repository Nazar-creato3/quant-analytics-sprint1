"""User email verification on signup."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import User, new_uuid
from app.domain.email_transactional import VerificationTokenORM
from app.services.auth.security_audit import write_security_audit
from app.services.email.pipeline import enqueue_email_job
from app.services.email.tokens import (
    VERIFICATION_TTL_HOURS,
    generate_raw_token,
    hash_token,
    is_expired,
    verification_expires_at,
    verify_token_hash,
)
from app.utils.cache import rate_limit_check

logger = get_logger(__name__)


def build_verification_url(raw_token: str) -> str:
    base = settings.EMAIL_VERIFICATION_BASE_URL.rstrip("/")
    return f"{base}/verify-email?token={raw_token}"


async def _invalidate_prior_tokens(db: AsyncSession, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(VerificationTokenORM)
        .where(VerificationTokenORM.user_id == user_id, VerificationTokenORM.used_at.is_(None))
        .values(used_at=now)
    )


async def send_verification_email_for_user(
    db: AsyncSession,
    user: User,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    if user.email_verified_at is not None:
        return

    raw_token = generate_raw_token()
    token_hash = hash_token(raw_token)
    await _invalidate_prior_tokens(db, user.id)
    token_row = VerificationTokenORM(
        id=new_uuid(),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=verification_expires_at(),
    )
    db.add(token_row)
    await db.flush()

    await enqueue_email_job(
        db,
        job_type="email_verification",
        template="email_verification",
        to_email=user.email,
        payload={
            "name": user.email.split("@")[0],
            "verify_url": build_verification_url(raw_token),
            "ttl_hours": VERIFICATION_TTL_HOURS,
        },
        user_id=user.id,
        entity_id=token_row.id,
    )
    await write_security_audit(
        db,
        event_type="verification_email_sent",
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
    )


async def resend_verification_email(
    db: AsyncSession,
    *,
    email: str,
    ip: str | None,
    user_agent: str | None,
) -> dict:
    normalized = email.lower().strip()
    allowed, _ = await rate_limit_check(
        f"verify:email:{normalized}",
        settings.VERIFICATION_RATE_LIMIT_PER_EMAIL,
        settings.VERIFICATION_RATE_LIMIT_WINDOW_SECONDS,
        fail_closed=True,
    )
    generic = {
        "ok": True,
        "message": "If an account exists and is unverified, a verification email has been sent.",
    }
    if not allowed:
        return generic

    result = await db.execute(select(User).where(User.email == normalized))
    user = result.scalar_one_or_none()
    if user and user.is_active and user.email_verified_at is None:
        await send_verification_email_for_user(db, user, ip=ip, user_agent=user_agent)
    return generic


async def confirm_email_verification(
    db: AsyncSession,
    *,
    raw_token: str,
    ip: str | None,
    user_agent: str | None,
) -> bool:
    token_hash = hash_token(raw_token.strip())
    result = await db.execute(
        select(VerificationTokenORM).where(VerificationTokenORM.token_hash == token_hash)
    )
    token_row = result.scalar_one_or_none()
    if not token_row:
        return False
    if not verify_token_hash(raw_token.strip(), token_row.token_hash):
        return False
    if token_row.used_at is not None:
        return False
    if is_expired(token_row.expires_at):
        return False

    user = await db.get(User, token_row.user_id)
    if not user or not user.is_active:
        return False

    now = datetime.now(timezone.utc)
    token_row.used_at = now
    user.email_verified_at = now

    await write_security_audit(
        db,
        event_type="email_verified",
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
    )
    return True


def user_needs_verification(user: User) -> bool:
    if not settings.REQUIRE_EMAIL_VERIFICATION:
        return False
    return user.email_verified_at is None
