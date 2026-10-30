"""Shared RBAC dependencies for API endpoints."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db
from app.db.models import User
from app.domain.rbac import IdentityORM, SystemRole, has_permission, map_legacy_user_role


async def get_user_and_role(db: AsyncSession, email: str) -> tuple[User, SystemRole]:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "User not found")
    role = map_legacy_user_role(user.role.value if hasattr(user.role, "value") else str(user.role))
    return user, role


async def require_permission(
    permission: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, SystemRole]:
    user, role = await get_user_and_role(db, email)
    if not has_permission(role, permission):
        raise HTTPException(403, f"Permission denied: {permission}")
    return user, role


async def get_identity_for_email(db: AsyncSession, email: str) -> IdentityORM | None:
    result = await db.execute(select(IdentityORM).where(IdentityORM.primary_email == email))
    return result.scalar_one_or_none()
