"""AES-256-GCM field-level encryption for broker tokens and PII."""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_NONCE_BYTES = 12


def _master_key() -> bytes | None:
    raw = settings.FIELD_ENCRYPTION_KEY.strip()
    if not raw:
        return None
    try:
        key = base64.urlsafe_b64decode(raw + "=" * ((4 - len(raw) % 4) % 4))
    except Exception:
        key = raw.encode("utf-8")
    if len(key) not in (16, 24, 32):
        key = key[:32].ljust(32, b"\0")
    return key


def encrypt_field(plaintext: str) -> str:
    """Return base64 envelope ciphertext or passthrough when encryption disabled."""
    if not plaintext:
        return plaintext
    key = _master_key()
    if key is None:
        return plaintext
    aes = AESGCM(key)
    nonce = os.urandom(_NONCE_BYTES)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt_field(ciphertext: str) -> str:
    if not ciphertext:
        return ciphertext
    key = _master_key()
    if key is None:
        return ciphertext
    try:
        blob = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        aes = AESGCM(key)
        return aes.decrypt(nonce, ct, None).decode("utf-8")
    except Exception as exc:
        logger.warning("Field decrypt failed", error=str(exc))
        return ciphertext
