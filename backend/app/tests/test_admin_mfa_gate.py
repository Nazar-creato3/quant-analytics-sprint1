"""Admin MFA enforcement and privilege-escalation tests."""
from __future__ import annotations

from app.domain.rbac import SystemRole, has_permission


def test_operator_admin_cannot_role_assign():
    assert not has_permission(SystemRole.OPERATOR_ADMIN, "role.assign")
    assert has_permission(SystemRole.OWNER_ADMIN, "role.assign")


def test_operator_explicit_deny_wildcard():
    assert not has_permission(SystemRole.OPERATOR_ADMIN, "*")


def test_require_admin_mfa_dependency_exists():
    from app.core.deps import require_admin_mfa

    assert callable(require_admin_mfa)


def test_admin_token_audience_configured():
    from app.core.config import settings

    assert settings.ADMIN_TOKEN_AUDIENCE == "admin"
    assert settings.ADMIN_ACCESS_TOKEN_COOKIE
