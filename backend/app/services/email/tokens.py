"""Cryptographically secure token generation and verification."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import settings

TOKEN_BYTES = 32  # 256 bits entropy
RECOVERY_TTL_MINUTES = 15
VERIFICATION_TTL_HOURS = 24


def generate_raw_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    material = f"{raw_token}:{settings.SECRET_KEY}".encode()
    return hashlib.sha256(material).hexdigest()


def verify_token_hash(raw_token: str, stored_hash: str) -> bool:
    computed = hash_token(raw_token)
    return hmac.compare_digest(computed, stored_hash)


def recovery_expires_at(*, now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return base + timedelta(minutes=RECOVERY_TTL_MINUTES)


def verification_expires_at(*, now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return base + timedelta(hours=VERIFICATION_TTL_HOURS)


def is_expired(expires_at: datetime, *, now: datetime | None = None) -> bool:
    base = now or datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return base >= expires_at
