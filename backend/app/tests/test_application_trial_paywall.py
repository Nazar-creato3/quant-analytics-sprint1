"""Security tests: trial paywall, WebAuthn device binding, application rate limits."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.account import router as account_router
from app.api.v1.endpoints.applications import router as applications_router
from app.api.v1.endpoints.auth import router as auth_router
from app.core.access_deps import require_paid_subscription
from app.core.deps import get_current_user_email, get_db, get_user_db
from app.db.models import User, UserRole
from app.domain.application_flow import (
    ApplicationORM,
    ApplicationStatus,
    PaywallSubscriptionStatus,
    UserSubscriptionStateORM,
    WebAuthnCredentialORM,
)
from app.services.application.service import hash_phone
from app.services.subscription.paywall import paywall_subscription_service
from app.services.webauthn.service import webauthn_service


def _make_trial_user() -> User:
    return User(
        id="user-trial-1",
        email="trial@example.com",
        hashed_password="dev::password123",
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=True,
        must_change_password=False,
        trial_started_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_trial_api_bypass_deposit_returns_403():
    """Direct API deposit while on trial (not paid) must return 403."""
    app = FastAPI()
    app.include_router(account_router, prefix="/api/v1")

    user = _make_trial_user()
    mock_db = AsyncMock()

    async def fake_get_user_db():
        yield mock_db

    async def fake_email():
        return user.email

    async def fake_require_paid():
        from fastapi import HTTPException

        raise HTTPException(403, "Paid subscription required")

    app.dependency_overrides[get_user_db] = fake_get_user_db
    app.dependency_overrides[get_current_user_email] = fake_email
    app.dependency_overrides[require_paid_subscription] = fake_require_paid

    with patch("app.api.v1.endpoints.account.paper_deposit", new=AsyncMock()) as mock_deposit:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/account/deposit",
                json={"amount_usd": 1000},
                headers={"Authorization": "Bearer fake"},
            )
    assert resp.status_code == 403
    mock_deposit.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_device_webauthn_login_rejected():
    """Login with WebAuthn assertion from a different credential is rejected."""
    db = AsyncMock()
    user_id = "user-1"
    bound_cred = WebAuthnCredentialORM(
        id="cred-row-1",
        user_id=user_id,
        credential_id="bound-credential-id",
        public_key=b"key",
        sign_count=0,
    )

    with (
        patch.object(webauthn_service, "has_credential", new=AsyncMock(return_value=True)),
        patch.object(webauthn_service, "get_credential", new=AsyncMock(return_value=bound_cred)),
        patch("app.services.webauthn.service.cache_get", new=AsyncMock(return_value="challenge-123")),
    ):
        with pytest.raises(ValueError, match="wrong_device"):
            await webauthn_service.verify_assertion(
                db,
                user_id,
                {
                    "id": "different-credential-id",
                    "response": {
                        "clientDataJSON": "eyJjaGFsbGVuZ2UiOiAiY2hhbGxlbmdlLTEyMyJ9",
                    },
                },
            )


@pytest.mark.asyncio
async def test_public_application_submit_disabled():
    """Legacy Turnstile/OTP application pipeline is closed."""
    app = FastAPI()
    app.include_router(applications_router, prefix="/api/v1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/applications/submit",
            json={
                "email": "new@example.com",
                "phone": "+79991234567",
                "name": "Test User",
                "turnstile_token": "test-token",
                "otp_code": "123456",
            },
        )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_paywall_subscription_trial_expires():
    """trial_active transitions to trial_expired after 2 days."""
    db = AsyncMock()
    row = UserSubscriptionStateORM(
        id="sub-1",
        user_id="user-1",
        subscription_status=PaywallSubscriptionStatus.TRIAL_ACTIVE.value,
        trial_start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    with patch.object(paywall_subscription_service, "get_or_create", new=AsyncMock(return_value=row)):
        status = await paywall_subscription_service.refresh_status(
            db, row, now=datetime(2026, 1, 5, tzinfo=timezone.utc)
        )
    assert status == PaywallSubscriptionStatus.TRIAL_EXPIRED


@pytest.mark.asyncio
async def test_payment_webhook_signature_required():
    """Payment unlock requires valid HMAC signature."""
    from app.api.v1.endpoints.origination import billing_router
    from app.core.config import settings

    app = FastAPI()
    app.include_router(billing_router, prefix="/api/v1")
    mock_db = AsyncMock()

    async def fake_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = fake_get_db

    with patch.object(settings, "PAYMENT_WEBHOOK_SECRET", "test-secret"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/billing/webhook/payment",
                json={
                    "event": "payment_succeeded",
                    "user_id": "user-1",
                    "external_ref": "pay-123",
                    "signature": "invalid",
                },
            )
        assert resp.status_code == 401

        sig = hmac.new(
            b"test-secret",
            b"payment_succeeded:user-1:pay-123",
            hashlib.sha256,
        ).hexdigest()
        with patch(
            "app.api.v1.endpoints.origination.admissions_service.grant_full_access",
            new=AsyncMock(),
        ) as grant:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp2 = await client.post(
                    "/api/v1/billing/webhook/payment",
                    json={
                        "event": "payment_succeeded",
                        "user_id": "user-1",
                        "external_ref": "pay-123",
                        "signature": sig,
                    },
                )
        assert resp2.status_code == 200
        grant.assert_awaited_once()


@pytest.mark.asyncio
async def test_paywall_snapshot_counts_down_from_48h():
    db = AsyncMock()
    row = UserSubscriptionStateORM(
        user_id="user-1",
        subscription_status=PaywallSubscriptionStatus.TRIAL_ACTIVE.value,
        trial_start_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    with patch.object(paywall_subscription_service, "get_or_create", new=AsyncMock(return_value=row)):
        with patch.object(
            paywall_subscription_service,
            "refresh_status",
            new=AsyncMock(return_value=PaywallSubscriptionStatus.TRIAL_ACTIVE),
        ):
            snap = await paywall_subscription_service.snapshot(db, "user-1")
    assert snap["paid"] is False
    assert snap["show_trial_timer"] is True
    assert snap["subscription_status"] == "trial_active"
    assert snap["trial_expires_at"].startswith("2026-01-03")


@pytest.mark.asyncio
async def test_paywall_snapshot_hides_timer_when_paid():
    db = AsyncMock()
    row = UserSubscriptionStateORM(
        user_id="user-1",
        subscription_status=PaywallSubscriptionStatus.PAID.value,
        trial_start_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    with patch.object(paywall_subscription_service, "get_or_create", new=AsyncMock(return_value=row)):
        with patch.object(
            paywall_subscription_service,
            "refresh_status",
            new=AsyncMock(return_value=PaywallSubscriptionStatus.PAID),
        ):
            snap = await paywall_subscription_service.snapshot(db, "user-1")
    assert snap["paid"] is True
    assert snap["show_trial_timer"] is False
    assert snap["trial_remaining_seconds"] == 0
    assert snap["trial_expires_at"] is None


@pytest.mark.asyncio
async def test_checkout_unavailable_without_yookassa():
    from app.api.v1.endpoints.origination import billing_router
    from app.core.config import settings

    app = FastAPI()
    app.include_router(billing_router, prefix="/api/v1")
    mock_db = AsyncMock()
    user = _make_trial_user()

    async def fake_get_db():
        yield mock_db

    async def fake_email():
        return user.email

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_current_user_email] = fake_email

    with (
        patch.object(settings, "YOOKASSA_SHOP_ID", ""),
        patch.object(settings, "YOOKASSA_SECRET_KEY", ""),
        patch(
            "app.api.v1.endpoints.origination._user",
            new=AsyncMock(return_value=user),
        ),
        patch(
            "app.api.v1.endpoints.origination.paywall_subscription_service.snapshot",
            new=AsyncMock(
                return_value={
                    "paid": False,
                    "subscription_status": "trial_active",
                    "trial_remaining_seconds": 100,
                    "trial_expires_at": None,
                }
            ),
        ),
        patch(
            "app.api.v1.endpoints.origination.rate_limit_check",
            new=AsyncMock(return_value=(True, 0)),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/billing/checkout")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_yookassa_webhook_rejects_unconfirmed_payment():
    from app.api.v1.endpoints.origination import billing_router
    from app.core.config import settings

    app = FastAPI()
    app.include_router(billing_router, prefix="/api/v1")
    mock_db = AsyncMock()

    async def fake_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = fake_get_db

    with (
        patch.object(settings, "YOOKASSA_SHOP_ID", "shop"),
        patch.object(settings, "YOOKASSA_SECRET_KEY", "secret"),
        patch(
            "app.api.v1.endpoints.origination.fetch_succeeded_payment_user_id",
            new=AsyncMock(return_value=None),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/billing/webhook/yookassa",
                json={"event": "payment.succeeded", "object": {"id": "pay-1"}},
            )
    assert resp.status_code == 401
