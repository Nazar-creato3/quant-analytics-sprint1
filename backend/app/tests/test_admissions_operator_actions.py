"""Operator one-click admissions actions: full access, admin, suspend."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.admissions import AdmissionStatus, display_bucket_for_status
from app.services.admissions.service import AdmissionsService


def test_display_buckets():
    assert display_bucket_for_status("trial") == "trial"
    assert display_bucket_for_status("lead") == "trial"
    assert display_bucket_for_status("paying") == "paying"
    assert display_bucket_for_status("approved") == "full"
    assert display_bucket_for_status("active") == "full"
    assert display_bucket_for_status("suspended") == "blocked"


@pytest.mark.asyncio
async def test_approve_uses_admin_override():
    svc = AdmissionsService()
    case = MagicMock(user_id=None)
    with patch.object(svc, "change_status", new=AsyncMock(return_value=case)) as change:
        await svc.approve_account(AsyncMock(), "case-1", actor_user_id="op")
    assert change.await_args.kwargs["admin_override"] is True
    assert change.await_args.args[2] == AdmissionStatus.APPROVED


@pytest.mark.asyncio
async def test_grant_admin_sets_admin_role():
    from app.db.models import UserRole

    svc = AdmissionsService()
    user = MagicMock(id="u1", email="a@b.c", role=UserRole.VIEWER)
    case = MagicMock(id="c1", user_id="u1", extra={}, contact_email="a@b.c")
    db = AsyncMock()
    with (
        patch.object(svc, "approve_account", new=AsyncMock(return_value=case)),
        patch.object(svc, "_linked_user", new=AsyncMock(return_value=user)),
        patch.object(svc, "_sync_identity_role", new=AsyncMock()),
        patch("app.services.admissions.service.audit.log", new=AsyncMock()),
    ):
        await svc.grant_admin(db, "c1", actor_user_id="op")
    assert user.role == UserRole.ADMIN
    assert user.is_whitelisted is True


@pytest.mark.asyncio
async def test_revoke_admin_keeps_membership():
    from app.db.models import UserRole

    svc = AdmissionsService()
    user = MagicMock(id="u1", email="a@b.c", role=UserRole.ADMIN, is_whitelisted=True)
    case = MagicMock(
        id="c1",
        user_id="u1",
        extra={"admin_granted": True},
        contact_email="a@b.c",
        status="approved",
    )
    db = AsyncMock()
    with (
        patch.object(svc, "get_case", new=AsyncMock(return_value=case)),
        patch.object(svc, "_linked_user", new=AsyncMock(return_value=user)),
        patch.object(svc, "_sync_identity_role", new=AsyncMock()) as sync_role,
        patch("app.services.admissions.service.audit.log", new=AsyncMock()),
    ):
        await svc.revoke_admin(db, "c1", actor_user_id="op")
    assert user.role == UserRole.VIEWER
    assert user.is_whitelisted is True
    sync_role.assert_awaited_once()
    assert sync_role.await_args.kwargs["admin"] is False
    assert case.extra["admin_granted"] is False


@pytest.mark.asyncio
async def test_suspend_limits_access_and_strips_admin():
    from app.db.models import UserRole
    from app.domain.access_policy import AccessLevel

    svc = AdmissionsService()
    user = MagicMock(id="u1", email="a@b.c", role=UserRole.ADMIN)
    case = MagicMock(id="c1", user_id="u1", extra={}, contact_email="a@b.c")
    db = AsyncMock()
    with (
        patch.object(svc, "change_status", new=AsyncMock(return_value=case)),
        patch.object(svc, "_linked_user", new=AsyncMock(return_value=user)),
        patch.object(svc, "_sync_identity_role", new=AsyncMock()),
        patch(
            "app.services.admissions.service.access_policy_service.set_level",
            new=AsyncMock(),
        ) as set_level,
        patch("app.services.admissions.service.audit.log", new=AsyncMock()),
    ):
        await svc.suspend_full_access(db, "c1", actor_user_id="op")
    assert user.role == UserRole.VIEWER
    assert user.is_whitelisted is False
    assert set_level.await_args.args[2] == AccessLevel.TRIAL_READ_ONLY
