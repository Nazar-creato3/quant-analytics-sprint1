"""Security audit log for auth-related events."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import new_uuid
from app.domain.email_transactional import SecurityAuditLogORM

logger = get_logger(__name__)


async def write_security_audit(
    db: AsyncSession,
    *,
    event_type: str,
    user_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    details: dict | None = None,
) -> None:
    entry = SecurityAuditLogORM(
        id=new_uuid(),
        user_id=user_id,
        event_type=event_type,
        ip=ip,
        user_agent=(user_agent or "")[:512] or None,
        details=details or {},
    )
    db.add(entry)
    logger.info(
        "Security audit",
        event_type=event_type,
        user_id=user_id,
        ip=ip,
    )
