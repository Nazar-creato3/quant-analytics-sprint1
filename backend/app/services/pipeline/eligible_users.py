"""Users eligible for scheduled per-user market-intelligence pipeline runs."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.domain.access_policy import AccessLevel, AccessPolicyStateORM

# Scheduled pipeline is heavy (LLM/ML per user). Trial users analyze on demand
# so adding many trial accounts cannot stall the whole platform.
_PIPELINE_EXCLUDED_LEVELS = frozenset(
    {
        AccessLevel.EXPIRED.value,
        AccessLevel.LOCKED.value,
        AccessLevel.TRIAL_READ_ONLY.value,
    }
)


async def list_pipeline_eligible_users(session: AsyncSession) -> list[User]:
    """Active users who may receive scheduled demo/live analysis (not expired/locked)."""
    result = await session.execute(
        select(User)
        .join(AccessPolicyStateORM, AccessPolicyStateORM.user_id == User.id)
        .where(
            User.is_active.is_(True),
            AccessPolicyStateORM.access_level.not_in(_PIPELINE_EXCLUDED_LEVELS),
        )
        .order_by(User.created_at)
    )
    return list(result.scalars().all())
