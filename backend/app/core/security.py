"""
Security utilities: JWT creation/verification, password hashing, whitelist enforcement.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError as JWTError
from jwt.exceptions import PyJWTError
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppEnv, settings
from app.core.logging import get_logger
from app.domain.refresh_token import RefreshTokenFamilyORM
from app.utils.helpers import new_uuid, utcnow

logger = get_logger(__name__)

# ── Password helpers ─────────────────────────────────────────────────────────

pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
    argon2__memory_cost=65536,
    argon2__time_cost=3,
    argon2__parallelism=4,
)


def hash_password(password: str) -> str:
    """Hash password.

    В development для удобства не используем bcrypt (чтобы не ловить 72-байтовый лимит и странные ошибки),
    а просто храним пароль в виде dev::<plain>. В staging/production используем bcrypt.
    """
    if settings.APP_ENV == AppEnv.DEVELOPMENT and settings.PASSWORD_DEV_PLAIN:
        return f"dev::{password}"
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify password; accepts legacy bcrypt and dev:: prefixes."""
    if hashed.startswith("dev::"):
        return settings.APP_ENV == AppEnv.DEVELOPMENT and hashed == f"dev::{plain}"
    # passlib 1.7.4 + bcrypt 4.1+ breaks bcrypt backend detection; verify legacy
    # hashes directly so existing users are not locked out after dependency upgrades.
    if hashed.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            import bcrypt

            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def password_needs_upgrade(hashed: str) -> bool:
    """True when stored hash should be re-hashed to argon2 after successful login."""
    if hashed.startswith("dev::"):
        return False
    return hashed.startswith(("$2a$", "$2b$", "$2y$"))


# ── JWT ──────────────────────────────────────────────────────────────────────

def create_access_token(
    subject: str,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    payload["type"] = "access"
    payload["jti"] = new_uuid()
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_admin_access_token(
    subject: str,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Admin contour JWT — distinct audience from user sessions."""
    claims = {"aud": settings.ADMIN_TOKEN_AUDIENCE, "is_admin": True}
    if extra_claims:
        claims.update(extra_claims)
    return create_access_token(subject, extra_claims=claims, expires_delta=expires_delta)


def _refresh_payload(subject: str, *, family_id: str, jti: str) -> dict[str, Any]:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
        "family_id": family_id,
        "jti": jti,
    }


def create_refresh_token(subject: str, *, family_id: str | None = None, jti: str | None = None) -> tuple[str, str, str]:
    """Create refresh JWT. Returns (token, family_id, jti)."""
    fid = family_id or new_uuid()
    token_jti = jti or new_uuid()
    payload = _refresh_payload(subject, family_id=fid, jti=token_jti)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM), fid, token_jti


async def register_refresh_family(db: AsyncSession, subject: str, family_id: str, jti: str) -> None:
    row = RefreshTokenFamilyORM(id=family_id, subject=subject, current_jti=jti, revoked=False)
    db.add(row)
    await db.flush()


async def rotate_refresh_token(
    db: AsyncSession,
    *,
    subject: str,
    family_id: str,
    presented_jti: str,
) -> tuple[str, str]:
    """Validate refresh token family, rotate jti. Raises ValueError on reuse/revocation."""
    result = await db.execute(
        select(RefreshTokenFamilyORM).where(RefreshTokenFamilyORM.id == family_id)
    )
    family = result.scalar_one_or_none()
    if not family or family.revoked or family.subject != subject:
        raise ValueError("Refresh token family revoked or unknown")
    if family.current_jti != presented_jti:
        family.revoked = True
        family.updated_at = utcnow()
        await db.flush()
        raise ValueError("Refresh token reuse detected")
    new_jti = new_uuid()
    family.current_jti = new_jti
    family.updated_at = utcnow()
    await db.flush()
    token, _, _ = create_refresh_token(subject, family_id=family_id, jti=new_jti)
    return token, new_jti


async def revoke_refresh_family(db: AsyncSession, family_id: str) -> bool:
    result = await db.execute(
        select(RefreshTokenFamilyORM).where(RefreshTokenFamilyORM.id == family_id)
    )
    family = result.scalar_one_or_none()
    if not family:
        return False
    family.revoked = True
    family.updated_at = utcnow()
    await db.flush()
    return True


async def revoke_all_refresh_families(db: AsyncSession, subject: str) -> int:
    result = await db.execute(
        select(RefreshTokenFamilyORM).where(
            RefreshTokenFamilyORM.subject == subject,
            RefreshTokenFamilyORM.revoked.is_(False),
        )
    )
    rows = list(result.scalars().all())
    for row in rows:
        row.revoked = True
        row.updated_at = utcnow()
    await db.flush()
    return len(rows)


_revoked_access_jti: set[str] = set()
_revoked_access_lock = Lock()


def revoke_access_jti(jti: str) -> None:
    """Refuse this access token after logout. Process-local until a shared store exists."""
    with _revoked_access_lock:
        _revoked_access_jti.add(jti)


def access_jti_revoked(jti: str | None) -> bool:
    if not isinstance(jti, str) or not jti:
        return False
    with _revoked_access_lock:
        return jti in _revoked_access_jti


def reset_revoked_access_jti() -> None:
    with _revoked_access_lock:
        _revoked_access_jti.clear()


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT. Raises JWTError on failure.

    ``algorithms`` is the configured algorithm (HS256 unless Settings says
    otherwise). The token ``alg`` header is not used to choose the key.
    ``exp`` and ``sub`` are required. See PyJWT 2.15.1
    ``jwt.decode`` / ``Options.require``.
    """
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        rejected_alg = (
            not isinstance(alg, str) or alg.lower() == "none" or alg != settings.ALGORITHM
        )
        if rejected_alg:
            raise JWTError("Invalid token algorithm")
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        return payload
    except JWTError as exc:
        logger.warning("JWT decode failed", error=str(exc))
        raise
    except PyJWTError as exc:
        logger.warning("JWT decode failed", error=str(exc))
        raise JWTError("Invalid token") from exc


# ── Whitelist ────────────────────────────────────────────────────────────────

def is_email_whitelisted(email: str) -> bool:
    """Check whether an email is in the configured whitelist."""
    return email.strip().lower() in settings.whitelist_emails_set


def require_whitelisted(email: str) -> None:
    """Raise ValueError if email is not whitelisted (except in dev)."""
    # В dev-окружении whitelist не блокирует регистрацию.
    if settings.APP_ENV == AppEnv.DEVELOPMENT:
        return

    if not is_email_whitelisted(email):
        logger.warning("Whitelist rejection", email=email)
        raise ValueError(f"Email {email!r} is not in the whitelist")