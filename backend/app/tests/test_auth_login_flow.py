"""Regression tests for multi-step login (WebAuthn + must_change_password flags)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.auth import router as auth_router
from app.core.deps import get_db
from app.db.models import User, UserRole


def _user(**overrides) -> User:
    base = dict(
        email="user@example.com",
        hashed_password="hashed",
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=True,
        must_change_password=False,
    )
    base.update(overrides)
    return User(**base)


def _make_app(user: User | None) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")

    async def fake_db():
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result)
        session.add = AsyncMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()
        yield session

    app.dependency_overrides[get_db] = fake_db
    return app


class TestLoginMultiStepFlags:
    def test_must_change_password_returns_flag_without_tokens(self):
        app = _make_app(_user(must_change_password=True))
        with patch("app.api.v1.endpoints.auth.rate_limit_peek", new=AsyncMock(return_value=(True, 9, 0))):
            with patch("app.api.v1.endpoints.auth.verify_password", return_value=True):
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.post(
                        "/api/v1/auth/login",
                        json={"email": "user@example.com", "password": "secret1234"},
                    )
        assert resp.status_code == 200
        body = resp.json()
        assert body["must_change_password"] is True
        assert body["access_token"] == ""
        assert body["refresh_token"] == ""

    def test_password_login_succeeds_without_webauthn_credentials(self):
        app = _make_app(_user())
        with patch("app.api.v1.endpoints.auth.rate_limit_peek", new=AsyncMock(return_value=(True, 9, 0))):
            with patch("app.api.v1.endpoints.auth.verify_password", return_value=True):
                with patch(
                    "app.api.v1.endpoints.auth.webauthn_service.has_credential",
                    new=AsyncMock(return_value=False),
                ):
                    with patch("app.api.v1.endpoints.auth.create_access_token", return_value="access"):
                        with patch(
                            "app.api.v1.endpoints.auth.create_refresh_token",
                            return_value=("refresh", "fam", "jti"),
                        ):
                            with patch(
                                "app.api.v1.endpoints.auth.register_refresh_family",
                                new=AsyncMock(),
                            ):
                                with patch(
                                    "app.api.v1.endpoints.auth.paywall_subscription_service.start_trial_on_first_login",
                                    new=AsyncMock(),
                                ):
                                    with TestClient(app, raise_server_exceptions=False) as client:
                                        resp = client.post(
                                            "/api/v1/auth/login",
                                            json={"email": "user@example.com", "password": "secret1234"},
                                        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] == "access"
        assert body["refresh_token"] == "refresh"
        assert body["webauthn_registration_required"] is False

    def test_webauthn_assert_required_without_tokens(self):
        app = _make_app(_user())
        with patch("app.api.v1.endpoints.auth.rate_limit_peek", new=AsyncMock(return_value=(True, 9, 0))):
            with patch("app.api.v1.endpoints.auth.verify_password", return_value=True):
                with patch(
                    "app.api.v1.endpoints.auth.webauthn_service.has_credential",
                    new=AsyncMock(return_value=True),
                ):
                    with TestClient(app, raise_server_exceptions=False) as client:
                        resp = client.post(
                            "/api/v1/auth/login",
                            json={"email": "user@example.com", "password": "secret1234"},
                        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["webauthn_required"] is True
        assert body["access_token"] == ""

    def test_full_login_returns_tokens_when_webauthn_asserted(self):
        app = _make_app(_user())
        with patch("app.api.v1.endpoints.auth.rate_limit_peek", new=AsyncMock(return_value=(True, 9, 0))):
            with patch("app.api.v1.endpoints.auth.verify_password", return_value=True):
                with patch(
                    "app.api.v1.endpoints.auth.webauthn_service.has_credential",
                    new=AsyncMock(return_value=True),
                ):
                    with patch(
                        "app.api.v1.endpoints.auth.webauthn_service.verify_assertion",
                        new=AsyncMock(),
                    ):
                        with patch("app.api.v1.endpoints.auth.create_access_token", return_value="access"):
                            with patch(
                                "app.api.v1.endpoints.auth.create_refresh_token",
                                return_value=("refresh", "fam", "jti"),
                            ):
                                with patch(
                                    "app.api.v1.endpoints.auth.register_refresh_family",
                                    new=AsyncMock(),
                                ):
                                    with patch(
                                        "app.api.v1.endpoints.auth.paywall_subscription_service.start_trial_on_first_login",
                                        new=AsyncMock(),
                                    ):
                                        with TestClient(app, raise_server_exceptions=False) as client:
                                            resp = client.post(
                                                "/api/v1/auth/login",
                                                json={
                                                    "email": "user@example.com",
                                                    "password": "secret1234",
                                                    "webauthn_credential": {"id": "cred"},
                                                },
                                            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] == "access"
        assert body["refresh_token"] == "refresh"
        assert body["webauthn_required"] is False
