"""Admin security contour — TOTP MFA + break-glass scaffold (Prompt 63)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.domain.rbac import SystemRole, TrustLevel, has_permission
from app.utils.helpers import new_uuid, utcnow


class BreakGlassRequestORM(Base):
    __tablename__ = "break_glass_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    requester_identity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approvals_needed: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    approvals_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approved_by: Mapped[str] = mapped_column(Text, nullable=False, default="")  # comma ids
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminMfaChallenge(BaseModel):
    identity_id: str
    code: str = Field(min_length=6, max_length=8)


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("utf-8").rstrip("=")


def totp_provisioning_uri(
    secret: str,
    *,
    account_name: str,
    issuer: str = "Quant Analytics",
    digits: int = 6,
    period: int = 30,
) -> str:
    """otpauth:// URI for Google Authenticator / Authy / any TOTP app."""
    from urllib.parse import quote

    label = quote(f"{issuer}:{account_name}")
    iss = quote(issuer)
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={iss}"
        f"&algorithm=SHA1&digits={digits}&period={period}"
    )


def _normalize_secret(secret: str) -> bytes:
    pad = "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(secret.upper() + pad, casefold=True)


def verify_totp(secret: str, code: str, *, window: int = 1, step: int = 30) -> bool:
    """Minimal TOTP (RFC 6238) verifier — no pyotp dependency required."""
    if not secret or not code or not code.isdigit():
        return False
    key = _normalize_secret(secret)
    counter = int(time.time()) // step
    for w in range(-window, window + 1):
        msg = struct.pack(">Q", counter + w)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
        token = f"{truncated % 1_000_000:06d}"
        if hmac.compare_digest(token, code.zfill(6)[-6:]):
            return True
    return False


SENSITIVE_ACTIONS = frozenset(
    {
        "role.assign",
        "identity.manage_permissions",
        "billing.admin",
        "device.override",
        "audit.disable",
        "break_glass.approve",
    }
)


def admin_path_allowed_for_role(role: SystemRole | str) -> bool:
    r = SystemRole(role) if not isinstance(role, SystemRole) else role
    return r in (SystemRole.OWNER_ADMIN, SystemRole.OPERATOR_ADMIN)


def requires_reauth(permission: str) -> bool:
    return permission in SENSITIVE_ACTIONS


def user_login_cannot_grant_admin(system_role: SystemRole | str) -> bool:
    """User login path must never elevate into admin zone."""
    return not admin_path_allowed_for_role(system_role)
