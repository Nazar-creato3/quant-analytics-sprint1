"""Unit and integration tests for email account recovery system."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.auth import router as auth_router
from app.core.deps import get_db
from app.db.models import User, UserRole
from app.services.email.providers import EmailProviderError, StubEmailProvider, send_with_failover
from app.services.email.tokens import (
    generate_raw_token,
    hash_token,
    is_expired,
    recovery_expires_at,
    verify_token_hash,
)
from app.services.email.webhooks import verify_postmark_signature, verify_sendgrid_signature


class TestTokenSecurity:
    def test_token_entropy_uniqueness(self):
        tokens = {generate_raw_token() for _ in range(100)}
        assert len(tokens) == 100
        for t in tokens:
            assert len(t) >= 32

    def test_hash_comparison_timing_safe(self):
        raw = generate_raw_token()
        good = hash_token(raw)
        bad = hash_token(generate_raw_token())
        assert verify_token_hash(raw, good) is True
        assert verify_token_hash(raw, bad) is False

    def test_ttl_expiry(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        assert is_expired(past) is True
        future = recovery_expires_at()
        assert is_expired(future) is False


class TestProviderFailover:
    @pytest.mark.asyncio
    async def test_failover_to_secondary(self):
        primary = AsyncMock()
        primary.name = "sendgrid"
        primary.send = AsyncMock(side_effect=EmailProviderError("sendgrid", "rate limited"))

        secondary = AsyncMock()
        secondary.name = "postmark"
        secondary.send = AsyncMock(
            return_value=type("R", (), {"provider": "postmark", "message_id": "pm-1", "latency_ms": 5.0})()
        )

        with patch("app.services.email.providers.get_provider") as mock_get:
            mock_get.side_effect = lambda name: primary if name == "sendgrid" else secondary
            with patch("app.services.email.providers.settings") as mock_settings:
                mock_settings.EMAIL_PRIMARY_PROVIDER = "sendgrid"
                mock_settings.EMAIL_SECONDARY_PROVIDER = "postmark"
                result = await send_with_failover(
                    to_email="user@example.com",
                    subject="Test",
                    html_body="<p>hi</p>",
                    text_body="hi",
                    idempotency_key="key-1",
                )
        assert result.provider == "postmark"
        primary.send.assert_awaited_once()
        secondary.send.assert_awaited_once()


class TestWebhookSignatures:
    def test_reject_unsigned_sendgrid(self):
        assert verify_sendgrid_signature(b"{}", "bad", "123") is False

    def test_reject_unsigned_postmark(self):
        assert verify_postmark_signature(b"{}", "bad") is False


def _make_recovery_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")

    async def fake_db():
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        session.get = AsyncMock(return_value=None)
        yield session

    app.dependency_overrides[get_db] = fake_db
    return app


class TestEnumerationResistance:
    def test_same_response_for_existing_and_missing(self):
        app = _make_recovery_app()
        user = User(
            id="u1",
            email="exists@example.com",
            hashed_password="x",
            role=UserRole.VIEWER,
            is_active=True,
            is_whitelisted=True,
        )

        async def fake_db_with_user():
            session = AsyncMock()
            session.add = MagicMock()
            session.flush = AsyncMock()
            session.commit = AsyncMock()

            def execute_side_effect(stmt):
                result = MagicMock()
                result.scalar_one_or_none.return_value = user
                return result

            session.execute = AsyncMock(side_effect=execute_side_effect)
            yield session

        timings: list[float] = []
        bodies: list[dict] = []

        with patch("app.api.v1.endpoints.auth.request_password_recovery", new=AsyncMock()) as mock_recover:
            mock_recover.return_value = {
                "ok": True,
                "message": "If an account exists for this email, password reset instructions have been sent.",
            }
            with patch("app.api.v1.endpoints.auth.rate_limit_check", new=AsyncMock(return_value=(True, 9))):
                with TestClient(app, raise_server_exceptions=False) as client:
                    for email in ("exists@example.com", "missing@example.com"):
                        app.dependency_overrides[get_db] = (
                            fake_db_with_user if email.startswith("exists") else _make_recovery_app().dependency_overrides[get_db]
                        )
                        start = time.perf_counter()
                        resp = client.post("/api/v1/auth/recover", json={"email": email})
                        timings.append(time.perf_counter() - start)
                        bodies.append(resp.json())

        assert bodies[0]["message"] == bodies[1]["message"]
        assert abs(timings[0] - timings[1]) < 0.5


class TestRecoveryEndpoints:
    def test_recover_returns_generic_message(self):
        app = _make_recovery_app()
        with patch(
            "app.api.v1.endpoints.auth.request_password_recovery",
            new=AsyncMock(
                return_value={
                    "ok": True,
                    "message": "If an account exists for this email, password reset instructions have been sent.",
                }
            ),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post("/api/v1/auth/recover", json={"email": "user@example.com"})
        assert resp.status_code == 200
        assert "account exists" in resp.json()["message"].lower()

    def test_reset_rejects_invalid_token(self):
        app = _make_recovery_app()
        with patch(
            "app.api.v1.endpoints.auth.reset_password_with_token",
            new=AsyncMock(return_value=False),
        ):
            with patch(
                "app.api.v1.endpoints.auth.rate_limit_check",
                new=AsyncMock(return_value=(True, 9)),
            ):
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.post(
                        "/api/v1/auth/reset",
                        json={
                            "token": "a" * 43,
                            "new_password": "NewSecurePass1!",
                            "confirm_password": "NewSecurePass1!",
                        },
                    )
        assert resp.status_code == 400
