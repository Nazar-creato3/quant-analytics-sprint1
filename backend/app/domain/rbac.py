"""RBAC Identity / Role / Permission schema (Prompt 61)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import new_uuid, utcnow


class TrustLevel(str, Enum):
    STANDARD = "standard"
    PRIVILEGED = "privileged"


class SystemRole(str, Enum):
    OWNER_ADMIN = "owner_admin"
    OPERATOR_ADMIN = "operator_admin"
    USER = "user"


# Explicit denies for operator_admin (hard list).
OPERATOR_EXPLICIT_DENY = frozenset(
    {
        "role.assign",
        "identity.manage_permissions",
        "security_policy.write",
        "audit.disable",
        "payment_rails.write",
        "*",
    }
)

ROLE_PERMISSIONS: dict[SystemRole, frozenset[str]] = {
    SystemRole.OWNER_ADMIN: frozenset({"*"}),
    SystemRole.OPERATOR_ADMIN: frozenset(
        {
            "crm.read",
            "crm.write",
            "trial.manage",
            "user.read",
            "user.suspend",
            "report.read",
            "risk.read",
            "chat.read",
            "chat.write",
            "chat.queue",
            "billing.manage",
            "ops.read",
        }
    ),
    SystemRole.USER: frozenset(
        {
            "profile.read",
            "portfolio.read",
            "trial.use",
            "billing.view",
            "chat.read",
            "chat.write",
        }
    ),
}


class IdentityORM(Base):
    __tablename__ = "identities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    primary_email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    trust_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TrustLevel.STANDARD.value, server_default="standard"
    )
    system_role: Mapped[str] = mapped_column(
        String(30), nullable=False, default=SystemRole.USER.value, server_default="user"
    )
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PermissionORM(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)


class RolePermissionORM(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role", "permission_code", name="uq_role_perm"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    role: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    permission_code: Mapped[str] = mapped_column(String(80), nullable=False)


class AccountGroupORM(Base):
    __tablename__ = "account_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    cluster_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def has_permission(role: SystemRole | str, permission: str) -> bool:
    """Authorization ALWAYS by permission string, never by role name alone."""
    r = SystemRole(role) if not isinstance(role, SystemRole) else role
    if permission in OPERATOR_EXPLICIT_DENY and r == SystemRole.OPERATOR_ADMIN:
        return False
    perms = ROLE_PERMISSIONS.get(r, frozenset())
    if "*" in perms:
        return True
    return permission in perms


def map_legacy_user_role(legacy: str) -> SystemRole:
    low = (legacy or "").lower()
    if low == "admin":
        return SystemRole.OWNER_ADMIN
    if low in ("analyst", "viewer"):
        return SystemRole.USER if low == "viewer" else SystemRole.OPERATOR_ADMIN
    return SystemRole.USER


def trust_level_for_role(role: SystemRole | str) -> TrustLevel:
    """Staff admins (owner + operator) get privileged device policy (multi-account)."""
    r = SystemRole(role) if not isinstance(role, SystemRole) else role
    if r in (SystemRole.OWNER_ADMIN, SystemRole.OPERATOR_ADMIN):
        return TrustLevel.PRIVILEGED
    return TrustLevel.STANDARD


def is_staff_admin_role(role: SystemRole | str) -> bool:
    r = SystemRole(role) if not isinstance(role, SystemRole) else role
    return r in (SystemRole.OWNER_ADMIN, SystemRole.OPERATOR_ADMIN)


class IdentityRead(BaseModel):
    id: str
    primary_email: str
    trust_level: str
    system_role: str
    mfa_enabled: bool
    user_id: str | None = None
