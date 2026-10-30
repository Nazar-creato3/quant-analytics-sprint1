"""RBAC permission matrix tests (Prompt 61)."""
from __future__ import annotations

from app.domain.rbac import OPERATOR_EXPLICIT_DENY, SystemRole, has_permission


def test_owner_has_wildcard():
    assert has_permission(SystemRole.OWNER_ADMIN, "crm.write")
    assert has_permission(SystemRole.OWNER_ADMIN, "role.assign")


def test_operator_crm_ok():
    assert has_permission(SystemRole.OPERATOR_ADMIN, "crm.read")
    assert has_permission(SystemRole.OPERATOR_ADMIN, "crm.write")


def test_operator_cannot_escalate():
    assert not has_permission(SystemRole.OPERATOR_ADMIN, "role.assign")
    assert not has_permission(SystemRole.OPERATOR_ADMIN, "identity.manage_permissions")
    for denied in OPERATOR_EXPLICIT_DENY:
        assert not has_permission(SystemRole.OPERATOR_ADMIN, denied)


def test_owner_can_manage_permissions():
    assert has_permission(SystemRole.OWNER_ADMIN, "identity.manage_permissions")
    assert has_permission(SystemRole.OWNER_ADMIN, "role.assign")


def test_trust_level_for_staff_admins():
    from app.domain.rbac import TrustLevel, trust_level_for_role

    assert trust_level_for_role(SystemRole.OWNER_ADMIN) == TrustLevel.PRIVILEGED
    assert trust_level_for_role(SystemRole.OPERATOR_ADMIN) == TrustLevel.PRIVILEGED
    assert trust_level_for_role(SystemRole.USER) == TrustLevel.STANDARD


def test_user_limited():
    assert has_permission(SystemRole.USER, "profile.read")
    assert not has_permission(SystemRole.USER, "crm.write")
