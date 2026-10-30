"""Encrypted credential storage for user trading keys (Vault-compatible path)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.field_encryption import decrypt_field, encrypt_field
from app.core.logging import get_logger
from app.services.trading_keys.key_access import record_access

logger = get_logger(__name__)


def vault_path_for(user_id: str, venue: str, account_mode: str) -> str:
    return f"users/{user_id}/venues/{venue}/{account_mode}"


def encrypt_credentials(payload: dict[str, Any]) -> str:
    return encrypt_field(json.dumps(payload, separators=(",", ":")))


def decrypt_credentials(blob: str) -> dict[str, Any]:
    raw = decrypt_field(blob)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Trading key decrypt produced non-JSON payload")
        return {}


async def load_credentials(
    db: AsyncSession,
    key_id: str,
    *,
    purpose: str,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    from app.domain.trading_keys import TradingKeySecretORM

    record_access(user_id=user_id, key_id=key_id, purpose=purpose)
    result = await db.execute(
        select(TradingKeySecretORM).where(TradingKeySecretORM.key_id == key_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return decrypt_credentials(row.encrypted_payload)


async def save_credentials(
    db: AsyncSession,
    *,
    key_id: str,
    payload: dict[str, Any],
) -> None:
    from app.domain.trading_keys import TradingKeySecretORM

    now = datetime.now(timezone.utc)
    encrypted = encrypt_credentials(payload)
    result = await db.execute(
        select(TradingKeySecretORM).where(TradingKeySecretORM.key_id == key_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.encrypted_payload = encrypted
        existing.updated_at = now
    else:
        db.add(
            TradingKeySecretORM(
                key_id=key_id,
                encrypted_payload=encrypted,
                created_at=now,
                updated_at=now,
            )
        )
