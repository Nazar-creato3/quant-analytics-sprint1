"""User-facing Google Authenticator TOTP (2FA) — secrets encrypted at rest."""
from __future__ import annotations

import hashlib
import hmac
import io
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from app.core.field_encryption import decrypt_field, encrypt_field
from app.domain.admin_security import generate_totp_secret, totp_provisioning_uri, verify_totp
from app.utils.cache import cache_delete, cache_get, cache_set

ISSUER = "Quant Analytics"
SETUP_TTL_SEC = 900
PENDING_LOGIN_TTL_SEC = 300
VERIFY_MAX_FAILURES = 5
VERIFY_LOCK_WINDOW_SEC = 900


def _backup_hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def generate_backup_codes(count: int = 10) -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ["".join(secrets.choice(alphabet) for _ in range(8)) for _ in range(count)]


def hash_backup_codes(codes: list[str]) -> list[str]:
    return [_backup_hash(c) for c in codes]


def consume_backup_code(stored_hashes: list[str] | None, code: str) -> tuple[bool, list[str] | None]:
    if not stored_hashes:
        return False, stored_hashes
    digest = _backup_hash(code)
    remaining: list[str] = []
    matched = False
    for h in stored_hashes:
        if not matched and hmac.compare_digest(h, digest):
            matched = True
            continue
        remaining.append(h)
    return matched, remaining if matched else list(stored_hashes)


def encrypt_totp_secret(secret: str) -> str:
    return encrypt_field(secret)


def decrypt_totp_secret(ciphertext: str) -> str:
    return decrypt_field(ciphertext)


def provisioning_uri(email: str, secret: str) -> str:
    return totp_provisioning_uri(secret, account_name=email, issuer=ISSUER)


def qr_code_data_url(uri: str) -> str:
    """PNG data-URL QR; falls back to empty string if qrcode is unavailable."""
    try:
        import base64

        import qrcode

        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


def setup_cache_key(user_id: str) -> str:
    return f"2fa:setup:{user_id}"


def pending_login_key(token_id: str) -> str:
    return f"2fa:pending:{token_id}"


def verify_fail_key(user_id: str) -> str:
    return f"2fa:fail:{user_id}"


async def store_setup_secret(user_id: str, secret: str) -> None:
    await cache_set(setup_cache_key(user_id), {"secret": secret}, ttl=SETUP_TTL_SEC)


async def load_setup_secret(user_id: str) -> str | None:
    raw = await cache_get(setup_cache_key(user_id))
    if isinstance(raw, dict) and isinstance(raw.get("secret"), str):
        return raw["secret"]
    return None


async def clear_setup_secret(user_id: str) -> None:
    await cache_delete(setup_cache_key(user_id))


async def store_pending_login(token_id: str, payload: dict[str, Any]) -> None:
    await cache_set(pending_login_key(token_id), payload, ttl=PENDING_LOGIN_TTL_SEC)


async def load_pending_login(token_id: str) -> dict[str, Any] | None:
    raw = await cache_get(pending_login_key(token_id))
    return raw if isinstance(raw, dict) else None


async def clear_pending_login(token_id: str) -> None:
    await cache_delete(pending_login_key(token_id))


def reauth_cache_key(user_id: str, token: str) -> str:
    return f"2fa:reauth:{user_id}:{token}"


async def consume_reauth_token(user_id: str, token: str | None) -> bool:
    """One-shot consume of a short-lived reauth marker. Returns True if valid."""
    if not token or not str(token).strip():
        return False
    key = reauth_cache_key(user_id, str(token).strip())
    raw = await cache_get(key)
    if not isinstance(raw, dict) or not raw.get("ok"):
        return False
    await cache_delete(key)
    return True


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def otpauth_manual_hint(secret: str, email: str) -> str:
    return (
        f"Issuer: {ISSUER}; Account: {email}; Secret: {secret}; "
        f"Digits: 6; Period: 30s; Algorithm: SHA1"
    )


__all__ = [
    "ISSUER",
    "VERIFY_LOCK_WINDOW_SEC",
    "VERIFY_MAX_FAILURES",
    "clear_pending_login",
    "clear_setup_secret",
    "consume_backup_code",
    "consume_reauth_token",
    "decrypt_totp_secret",
    "encrypt_totp_secret",
    "generate_backup_codes",
    "generate_totp_secret",
    "hash_backup_codes",
    "load_pending_login",
    "load_setup_secret",
    "otpauth_manual_hint",
    "pending_login_key",
    "provisioning_uri",
    "qr_code_data_url",
    "quote",
    "reauth_cache_key",
    "store_pending_login",
    "store_setup_secret",
    "utcnow",
    "verify_fail_key",
    "verify_totp",
]
