"""Structured security audit events (auth, admin, broker-gateway)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AuditLog

logger = get_logger(__name__)


async def log_security_event(
    db: AsyncSession,
    *,
    action: str,
    user_id: str | None = None,
    resource_type: str = "security",
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
    success: bool = True,
    error: str | None = None,
) -> None:
    """Append-only security event (immutable audit trail)."""
    row = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        ip_address=ip,
        success=success,
        error=error,
    )
    db.add(row)
    await db.flush()
    logger.info(
        "security_event",
        action=action,
        user_id=user_id,
        success=success,
        resource_type=resource_type,
    )
