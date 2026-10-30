"""Admin-issued platform logins (invite-only origination)."""
from __future__ import annotations

import secrets
import string

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import User, UserRole
from app.services.application.email_verification import send_credentials_email
from app.utils.helpers import utcnow


def generate_temp_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def provision_whitelisted_login(
    db: AsyncSession, email: str
) -> tuple[User, str | None]:
    """Create or whitelist a user. Returns plaintext password only for new accounts."""
    normalized = email.strip().lower()
    result = await db.execute(select(User).where(User.email == normalized))
    user = result.scalar_one_or_none()
    if user:
        user.is_whitelisted = True
        user.is_active = True
        if user.email_verified_at is None:
            user.email_verified_at = utcnow()
        await db.flush()
        return user, None

    plaintext = generate_temp_password()
    user = User(
        email=normalized,
        hashed_password=hash_password(plaintext),
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=True,
        must_change_password=True,
        email_verified_at=utcnow(),
    )
    db.add(user)
    await db.flush()
    await send_credentials_email(normalized, plaintext)
    return user, plaintext
