"""Append-only audit trail for order / maneuver placement requests (blueprint §9)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.utils.json_safe import sanitize_for_json

logger = get_logger(__name__)


async def record_trading_placement_request(
    db: AsyncSession,
    *,
    user_id: str | None,
    actor_email: str | None,
    resource_type: str,
    resource_id: str,
    symbol: str,
    side: str,
    broker_mode: str,
    trading_mode: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    commit: bool = True,
) -> str:
    """Insert immutable placement audit row. Returns new row id."""
    from app.db.models import TradingPlacementAudit

    row_id = str(uuid.uuid4())
    row = TradingPlacementAudit(
        id=row_id,
        timestamp=datetime.now(timezone.utc),
        user_id=user_id,
        actor_email=(actor_email or "").lower() or None,
        resource_type=resource_type,
        resource_id=resource_id,
        symbol=symbol.upper(),
        side=side.lower(),
        broker_mode=broker_mode,
        trading_mode=trading_mode,
        details=sanitize_for_json(details or {}),
        ip_address=ip_address,
    )
    db.add(row)
    if commit:
        await db.commit()
    else:
        await db.flush()
    logger.info(
        "trading_placement_audit",
        audit_id=row_id,
        symbol=symbol,
        side=side,
        broker_mode=broker_mode,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    return row_id


def resolve_broker_mode(*, live_unlocked: bool, paper_sim: bool) -> str:
    if live_unlocked:
        return "live"
    if paper_sim:
        return "paper_sim"
    return "paper_broker"
