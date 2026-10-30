"""Tests for Admissions CRM state machine (Prompt 57)."""
from __future__ import annotations

import pytest

from app.domain.admissions import (
    AdmissionStatus,
    AdmissionTransitionError,
    assert_admission_transition,
)


def test_lead_to_trial_ok():
    assert_admission_transition(AdmissionStatus.LEAD, AdmissionStatus.TRIAL)


def test_lead_to_offboarded_ok():
    assert_admission_transition(AdmissionStatus.LEAD, AdmissionStatus.OFFBOARDED)


def test_admin_override_allows_any_transition():
    assert_admission_transition(
        AdmissionStatus.LEAD,
        AdmissionStatus.ACTIVE,
        admin_override=True,
    )


def test_active_to_lead_illegal():
    with pytest.raises(AdmissionTransitionError):
        assert_admission_transition(AdmissionStatus.ACTIVE, AdmissionStatus.LEAD)


def test_qualified_to_approved_ok():
    assert_admission_transition(AdmissionStatus.QUALIFIED, AdmissionStatus.APPROVED)


def test_rejected_requires_reason_path_still_transitionable_to_lead():
    assert_admission_transition(AdmissionStatus.REJECTED, AdmissionStatus.LEAD)


@pytest.mark.parametrize(
    "current,target",
    [
        (AdmissionStatus.LEAD, AdmissionStatus.ACTIVE),
        (AdmissionStatus.TRIAL, AdmissionStatus.PAYING),
        (AdmissionStatus.OFFBOARDED, AdmissionStatus.ACTIVE),
    ],
)
def test_illegal_jumps(current, target):
    with pytest.raises(AdmissionTransitionError):
        assert_admission_transition(current, target)


@pytest.mark.asyncio
async def test_change_status_endpoint_owner_admin_offboard():
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock, patch

    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI

    from app.api.v1.endpoints.admissions import router as admissions_router
    from app.core.deps import get_current_user_email, get_db
    from app.domain.admissions import AdmissionCaseRead, AdmissionStatus
    from app.domain.rbac import SystemRole

    app = FastAPI()
    app.include_router(admissions_router, prefix="/api/v1")

    mock_db = AsyncMock()
    mock_user = MagicMock(id="owner-1")
    mock_case = AdmissionCaseRead(
        id="case-1",
        status=AdmissionStatus.OFFBOARDED,
        source="manual",
        contact_email="lead@example.com",
        contact_name="Lead",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    async def fake_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_current_user_email] = lambda: "owner@test.com"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch(
                "app.api.v1.endpoints.admissions.get_user_and_role",
                new=AsyncMock(return_value=(mock_user, SystemRole.OWNER_ADMIN)),
            ),
            patch(
                "app.api.v1.endpoints.admissions.admissions_service.change_status",
                new=AsyncMock(return_value=mock_case),
            ) as mock_change,
            patch(
                "app.api.v1.endpoints.admissions.admissions_service.to_read",
                return_value=mock_case,
            ),
        ):
            resp = await client.post(
                "/api/v1/admissions/case-1/status",
                json={"status": "offboarded"},
            )

    assert resp.status_code == 200
    mock_change.assert_awaited_once()
    assert mock_change.await_args.args[2] == AdmissionStatus.OFFBOARDED
    assert mock_change.await_args.kwargs["admin_override"] is True


@pytest.mark.asyncio
async def test_change_status_endpoint_operator_admin_offboard_lead():
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock, patch

    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI

    from app.api.v1.endpoints.admissions import router as admissions_router
    from app.core.deps import get_current_user_email, get_db
    from app.domain.admissions import AdmissionCaseRead, AdmissionStatus
    from app.domain.rbac import SystemRole

    app = FastAPI()
    app.include_router(admissions_router, prefix="/api/v1")

    mock_db = AsyncMock()
    mock_user = MagicMock(id="ops-1")
    mock_case = AdmissionCaseRead(
        id="case-1",
        status=AdmissionStatus.OFFBOARDED,
        source="manual",
        contact_email="lead@example.com",
        contact_name="Lead",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    async def fake_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_current_user_email] = lambda: "ops@test.com"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch(
                "app.api.v1.endpoints.admissions.get_user_and_role",
                new=AsyncMock(return_value=(mock_user, SystemRole.OPERATOR_ADMIN)),
            ),
            patch(
                "app.api.v1.endpoints.admissions.admissions_service.change_status",
                new=AsyncMock(return_value=mock_case),
            ) as mock_change,
            patch(
                "app.api.v1.endpoints.admissions.admissions_service.to_read",
                return_value=mock_case,
            ),
        ):
            resp = await client.post(
                "/api/v1/admissions/case-1/status",
                json={"status": "offboarded"},
            )

    assert resp.status_code == 200
    mock_change.assert_awaited_once()
    assert mock_change.await_args.args[2] == AdmissionStatus.OFFBOARDED
    assert mock_change.await_args.kwargs["admin_override"] is False
