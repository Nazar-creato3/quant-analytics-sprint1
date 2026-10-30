"""Access-policy dependencies for trial gating."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db
from app.core.rbac_deps import get_user_and_role
from app.db.models import User
from app.domain.access_policy import AccessAction, AccessLevel
from app.domain.rbac import SystemRole, has_permission
from app.services.access_policy.service import access_policy_service


async def require_access_action(
    action: AccessAction,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> User:
    user, _ = await get_user_and_role(db, email)
    if not await access_policy_service.can(db, user.id, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Action not permitted at current access level: {action.value}",
        )
    return user


def require_access(action: AccessAction):
    """FastAPI dependency factory for a specific access action."""

    async def _dep(
        email: str = Depends(get_current_user_email),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        return await require_access_action(action, email=email, db=db)

    return _dep


async def require_post_trial(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Block expired/locked accounts. Trial users keep demo analysis and paper trading."""
    user, role = await get_user_and_role(db, email)
    if role in (SystemRole.OWNER_ADMIN, SystemRole.OPERATOR_ADMIN):
        return user
    if has_permission(role, "*") or has_permission(role, "ops.read"):
        return user
    policy = await access_policy_service.read(db, user.id)
    if policy.access_level in (AccessLevel.EXPIRED, AccessLevel.LOCKED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ приостановлен. Обратитесь в поддержку или продлите подписку.",
        )
    return user


async def require_owner_admin(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Only platform owner admins (legacy role=admin)."""
    user, role = await get_user_and_role(db, email)
    if role != SystemRole.OWNER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner admin access required")
    return user


async def require_crm_read(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> User:
    user, role = await get_user_and_role(db, email)
    if not has_permission(role, "crm.read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CRM access denied")
    return user


async def require_crm_write(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> User:
    user, role = await get_user_and_role(db, email)
    if not has_permission(role, "crm.write"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CRM write denied")
    return user


async def require_ops_read(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Platform ops (venue keys, drills, macro registry mutations)."""
    user, role = await get_user_and_role(db, email)
    if not has_permission(role, "ops.read") and not has_permission(role, "*"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops.read required")
    return user


async def require_paid_subscription(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Server-side paywall: balance/deposit endpoints require paid subscription."""
    user, role = await get_user_and_role(db, email)
    if role in (SystemRole.OWNER_ADMIN, SystemRole.OPERATOR_ADMIN):
        return user
    if has_permission(role, "*") or has_permission(role, "ops.read"):
        return user
    from app.services.subscription.paywall import paywall_subscription_service

    if not await paywall_subscription_service.is_paid(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Paid subscription required for balance and deposit operations.",
        )
    return user
