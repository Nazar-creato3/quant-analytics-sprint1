"""Resolve active user trading credentials (Flow B). Never falls back to platform keys."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.trading_keys import TradingKeyMetadataORM
from app.services.trading_keys.audit import log_trading_key_action
from app.services.trading_keys.store import decrypt_credentials, load_credentials


@dataclass
class UserVenueCredentials:
    key_id: str
    user_id: str
    venue: str
    account_mode: str
    credentials: dict[str, Any]
    account_display: str | None


class UserTradingKeyNotFound(Exception):
    pass


async def get_active_user_credentials(
    db: AsyncSession,
    *,
    user_id: str,
    venue: str,
    account_mode: str = "live",
    action: str = "key_used",
) -> UserVenueCredentials:
    result = await db.execute(
        select(TradingKeyMetadataORM).where(
            TradingKeyMetadataORM.user_id == user_id,
            TradingKeyMetadataORM.venue == venue.lower(),
            TradingKeyMetadataORM.account_mode == account_mode,
            TradingKeyMetadataORM.status == "active",
            TradingKeyMetadataORM.revoked_at.is_(None),
        )
    )
    meta = result.scalar_one_or_none()
    if meta is None:
        raise UserTradingKeyNotFound(f"No active {venue} key for user")

    creds = await load_credentials(db, meta.id, purpose="execution", user_id=user_id)
    if not creds:
        raise UserTradingKeyNotFound(f"Missing encrypted credentials for {venue}")

    meta.last_used_at = datetime.now(timezone.utc)
    await log_trading_key_action(
        db,
        user_id=user_id,
        key_id=meta.id,
        venue=venue,
        action=action,
        meta={"account_mode": account_mode},
    )
    return UserVenueCredentials(
        key_id=meta.id,
        user_id=user_id,
        venue=meta.venue,
        account_mode=meta.account_mode,
        credentials=creds,
        account_display=meta.account_display,
    )


async def list_user_connected_venues(
    db: AsyncSession,
    user_id: str,
) -> list[TradingKeyMetadataORM]:
    result = await db.execute(
        select(TradingKeyMetadataORM).where(
            TradingKeyMetadataORM.user_id == user_id,
            TradingKeyMetadataORM.status == "active",
            TradingKeyMetadataORM.revoked_at.is_(None),
        )
    )
    return list(result.scalars().all())
