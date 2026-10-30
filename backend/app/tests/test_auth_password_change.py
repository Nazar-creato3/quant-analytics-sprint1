"""Tests for email-confirmed password change flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.auth import router as auth_router
from app.core.deps import get_current_user_email, get_db
from app.db.models import User, UserRole


def _user(**overrides) -> User:
    base = dict(
        id="user-1",
        email="user@example.com",
        hashed_password="oldhash",
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=True,
        must_change_password=False,
    )
    base.update(overrides)
    return User(**base)


def _make_app(user: User) -> FastAPI:
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
    app.dependency_overrides[get_current_user_email] = lambda: user.email
    return app


class TestPasswordChangeFlow:
    def test_request_sends_token(self):
        app = _make_app(_user())
        with patch(
            "app.api.v1.endpoints.auth.request_password_change",
            new=AsyncMock(return_value="123456"),
        ) as mock_request:
            with patch(
                "app.api.v1.endpoints.auth.rate_limit_check",
                new=AsyncMock(return_value=(True, 4)),
            ):
                with patch("app.api.v1.endpoints.auth.settings") as mock_settings:
                    mock_settings.is_development = True
                    with TestClient(app, raise_server_exceptions=False) as client:
                        resp = client.post(
                            "/api/v1/auth/password-change/request",
                            json={
                                "new_password": "NewSecurePass1!",
                                "confirm_password": "NewSecurePass1!",
                            },
                        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["dev_code"] == "123456"
        mock_request.assert_awaited_once()

    def test_confirm_changes_hash(self):
        app = _make_app(_user())
        with patch(
            "app.api.v1.endpoints.auth.confirm_password_change",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "app.api.v1.endpoints.auth.rate_limit_check",
                new=AsyncMock(return_value=(True, 4)),
            ):
                with patch(
                    "app.api.v1.endpoints.auth.apply_new_password_hash",
                    return_value="$argon2id$newhash",
                ):
                    with patch(
                        "app.api.v1.endpoints.auth.revoke_all_refresh_families",
                        new=AsyncMock(return_value=1),
                    ):
                        with TestClient(app, raise_server_exceptions=False) as client:
                            resp = client.post(
                                "/api/v1/auth/password-change/confirm",
                                json={
                                    "new_password": "NewSecurePass1!",
                                    "confirm_password": "NewSecurePass1!",
                                    "code": "123456",
                                },
                            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_wrong_token_rejected(self):
        app = _make_app(_user())
        with patch(
            "app.api.v1.endpoints.auth.confirm_password_change",
            new=AsyncMock(return_value=False),
        ):
            with patch(
                "app.api.v1.endpoints.auth.rate_limit_check",
                new=AsyncMock(return_value=(True, 4)),
            ):
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.post(
                        "/api/v1/auth/password-change/confirm",
                        json={
                            "new_password": "NewSecurePass1!",
                            "confirm_password": "NewSecurePass1!",
                            "code": "000000",
                        },
                    )
        assert resp.status_code == 400

    def test_mismatched_passwords_rejected(self):
        app = _make_app(_user())
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/password-change/request",
                json={
                    "new_password": "NewSecurePass1!",
                    "confirm_password": "DifferentPass1!",
                },
            )
        assert resp.status_code == 422
