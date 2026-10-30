"""Tests for login endpoint rate limiting (SEC-04)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.auth import router as auth_router
from app.core.deps import get_db


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")

    async def fake_db():
        session = AsyncMock()
        result = AsyncMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        session.add = AsyncMock()
        session.commit = AsyncMock()
        yield session

    app.dependency_overrides[get_db] = fake_db
    return app


class TestLoginRateLimit:
    def test_returns_429_when_rate_limit_exceeded(self):
        app = _make_app()
        with patch(
            "app.api.v1.endpoints.auth.rate_limit_peek",
            new=AsyncMock(return_value=(False, 0, 120)),
        ) as mock_peek:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/api/v1/auth/login",
                    json={"email": "user@example.com", "password": "secret12"},
                )

        assert resp.status_code == 429
        assert "неудачных попыток" in resp.json()["detail"]
        assert resp.headers.get("retry-after") == "120"
        mock_peek.assert_awaited_once()

    def test_password_verify_skipped_when_rate_limited(self):
        app = _make_app()
        with patch(
            "app.api.v1.endpoints.auth.rate_limit_peek",
            new=AsyncMock(return_value=(False, 0, 60)),
        ):
            with patch("app.api.v1.endpoints.auth.verify_password") as mock_verify:
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.post(
                        "/api/v1/auth/login",
                        json={"email": "user@example.com", "password": "secret12"},
                    )

        assert resp.status_code == 429
        mock_verify.assert_not_called()

    def test_failed_password_records_failure_not_successful_login(self):
        from app.db.models import User, UserRole

        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")

        user = User(
            email="user@example.com",
            hashed_password="hashed",
            role=UserRole.VIEWER,
            is_active=True,
            is_whitelisted=True,
        )

        async def fake_db():
            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = user
            session.execute = AsyncMock(return_value=result)
            session.add = AsyncMock()
            session.commit = AsyncMock()
            yield session

        app.dependency_overrides[get_db] = fake_db

        with patch(
            "app.api.v1.endpoints.auth.rate_limit_peek",
            new=AsyncMock(return_value=(True, 9, 0)),
        ) as mock_peek:
            with patch(
                "app.api.v1.endpoints.auth.rate_limit_record_failure",
                new=AsyncMock(),
            ) as mock_record:
                with patch("app.api.v1.endpoints.auth.verify_password", return_value=True):
                    with patch(
                        "app.api.v1.endpoints.auth.webauthn_service.has_credential",
                        new=AsyncMock(return_value=False),
                    ):
                        with patch(
                            "app.api.v1.endpoints.auth.create_access_token",
                            return_value="access",
                        ):
                            with patch(
                                "app.api.v1.endpoints.auth.create_refresh_token",
                                return_value=("refresh", "fam", "jti"),
                            ):
                                with patch(
                                    "app.api.v1.endpoints.auth.register_refresh_family",
                                    new=AsyncMock(),
                                ):
                                    with patch(
                                        "app.api.v1.endpoints.auth.rate_limit_clear",
                                        new=AsyncMock(),
                                    ):
                                        with patch(
                                            "app.api.v1.endpoints.auth.paywall_subscription_service.start_trial_on_first_login",
                                            new=AsyncMock(),
                                        ):
                                            with TestClient(app, raise_server_exceptions=False) as client:
                                                resp = client.post(
                                                    "/api/v1/auth/login",
                                                    json={"email": "user@example.com", "password": "secret12"},
                                                )

        assert resp.status_code == 200
        assert resp.json()["access_token"] == "access"
        mock_peek.assert_awaited()
        mock_record.assert_not_awaited()


class TestRateLimitFailClosed:
    @pytest.mark.asyncio
    async def test_fail_closed_denies_on_redis_error(self):
        from app.utils import cache as cache_mod

        with patch.object(cache_mod, "_get_redis", side_effect=ConnectionError("down")):
            allowed, remaining, retry_after = await cache_mod.rate_limit_peek(
                "login:1.2.3.4", 10, fail_closed=True
            )
        assert allowed is False
        assert remaining == 0
        assert retry_after == 300

    @pytest.mark.asyncio
    async def test_fail_open_allows_on_redis_error_by_default(self):
        from app.utils import cache as cache_mod

        with patch.object(cache_mod, "_get_redis", side_effect=ConnectionError("down")):
            allowed, remaining, retry_after = await cache_mod.rate_limit_peek(
                "other:1.2.3.4", 5
            )
        assert allowed is True
        assert remaining == 5
        assert retry_after == 0
