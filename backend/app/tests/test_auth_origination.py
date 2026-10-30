"""Origination auth — open registration helpers and public apply route."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.endpoints.auth import _login_allowed, _registration_allowed
from app.core.config import settings
from app.db.models import User, UserRole
from app.domain.rbac import TrustLevel
from app.services.device_identity.service import device_identity_service


def test_registration_default_closed():
    assert settings.OPEN_REGISTRATION is False


def test_registration_closed_without_approved_legal(monkeypatch):
    from app.core.config import AppEnv

    monkeypatch.setattr(settings, "OPEN_REGISTRATION", False)
    monkeypatch.setattr(settings, "QA_E2E_DEMO", False)
    monkeypatch.setattr(settings, "APP_ENV", AppEnv.PRODUCTION)
    assert _registration_allowed("stranger@example.com") is False


def test_registration_open_on_demo_drafts(monkeypatch):
    monkeypatch.setattr(settings, "QA_E2E_DEMO", True)
    assert _registration_allowed("stranger@example.com") is True


def test_login_allowed_for_active_user_when_open(monkeypatch):
    monkeypatch.setattr(settings, "OPEN_REGISTRATION", True)
    user = User(
        email="u@example.com",
        hashed_password="x",
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=False,
    )
    assert _login_allowed(user) is True


def test_login_blocked_when_not_whitelisted_and_closed(monkeypatch):
    monkeypatch.setattr(settings, "OPEN_REGISTRATION", False)
    user = User(
        email="u@example.com",
        hashed_password="x",
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=False,
    )
    assert _login_allowed(user) is False


@pytest.mark.asyncio
async def test_resolve_effective_trust_does_not_inherit_device_privilege():
    """Standard user on admin workstation must not get privileged device policy."""
    db = AsyncMock()
    with patch.object(
        device_identity_service,
        "resolve_trust_level",
        new=AsyncMock(return_value=TrustLevel.STANDARD),
    ) as mock_user_trust:
        trust = await device_identity_service.resolve_effective_trust(
            db, "stranger@example.com", device_id="device-admin-used"
        )
    assert trust == TrustLevel.STANDARD
    mock_user_trust.assert_awaited_once()


@pytest.mark.asyncio
async def test_public_admission_apply_endpoint():
    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI

    from app.api.v1.endpoints.admissions import router as admissions_router
    from app.core.deps import get_db

    app = FastAPI()
    app.include_router(admissions_router, prefix="/api/v1")

    mock_db = AsyncMock()
    mock_case = type(
        "Case",
        (),
        {
            "id": "case-1",
            "status": "lead",
            "source": "web_application",
            "jurisdiction": None,
            "capital_range": None,
            "experience_level": None,
            "strategy_interest": None,
            "owner_user_id": None,
            "contact_email": "lead@example.com",
            "contact_name": "Lead",
            "contact_phone": None,
            "user_id": None,
            "notes": None,
            "extra": {},
            "created_at": None,
            "updated_at": None,
        },
    )()

    async def fake_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = fake_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch(
                "app.api.v1.endpoints.admissions.rate_limit_check",
                new=AsyncMock(return_value=(True, 9)),
            ),
            patch(
                "app.api.v1.endpoints.admissions.score_signup_abuse_async",
                new=AsyncMock(),
            ) as mock_abuse,
            patch(
                "app.api.v1.endpoints.admissions.admissions_service.create_lead",
                new=AsyncMock(return_value=mock_case),
            ) as mock_create,
            patch(
                "app.api.v1.endpoints.admissions.admissions_service.to_read_enriched",
                new=AsyncMock(),
            ) as mock_read,
            patch(
                "app.services.legal.gates.registration_open",
                return_value=True,
            ),
        ):
            from app.domain.admissions import AdmissionCaseRead, AdmissionStatus
            from datetime import datetime, timezone

            mock_abuse.return_value.decision_hint = "allow"
            mock_read.return_value = AdmissionCaseRead(
                id="case-1",
                status=AdmissionStatus.LEAD,
                source="web_application",
                contact_email="lead@example.com",
                contact_name="Lead",
                trial_used=False,
                has_platform_account=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            resp = await client.post(
                "/api/v1/admissions/apply",
                json={"contact_email": "lead@example.com", "contact_name": "Lead"},
            )

    assert resp.status_code == 201
    mock_create.assert_awaited_once()
