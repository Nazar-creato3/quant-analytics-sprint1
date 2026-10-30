"""Audit log helper for trading key lifecycle."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.trading_keys import TradingKeyAuditORM


async def log_trading_key_action(
    db: AsyncSession,
    *,
    user_id: str,
    action: str,
    key_id: str | None = None,
    venue: str | None = None,
    actor_user_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    db.add(
        TradingKeyAuditORM(
            id=str(uuid.uuid4()),
            user_id=user_id,
            key_id=key_id,
            venue=venue,
            action=action,
            actor_user_id=actor_user_id or user_id,
            meta=meta or {},
            created_at=datetime.now(timezone.utc),
        )
    )
