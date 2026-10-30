"""Abuse hardening: session gates, IDOR, unauthenticated brute-force surfaces."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.auth import _session_denied_detail, router as auth_router
from app.api.v1.endpoints.origination import billing_router, subport_router
from app.core.deps import get_current_user_email, get_db
from app.db.models import User, UserRole


def _user(**overrides) -> User:
    base = dict(
        id="user-1",
        email="trial@example.com",
        hashed_password="hashed",
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=True,
        must_change_password=False,
        email_verified_at=None,
    )
    base.update(overrides)
    return User(**base)


def test_unverified_session_denied_when_flag_on(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)
    user = _user()
    assert _session_denied_detail(user) is not None


def test_verified_session_allowed(monkeypatch):
    from datetime import datetime, timezone

    from app.core.config import settings

    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)
    user = _user(email_verified_at=datetime.now(timezone.utc))
    assert _session_denied_detail(user) is None


@pytest.mark.asyncio
async def test_change_password_does_not_enumerate_users():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=result)

    async def fake_db():
        yield mock_db

    app.dependency_overrides[get_db] = fake_db
    with patch(
        "app.api.v1.endpoints.auth._enforce_login_rate_limit", new=AsyncMock()
    ), patch(
        "app.api.v1.endpoints.auth._record_failed_login", new=AsyncMock()
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/auth/change-password",
                json={
                    "email": "nobody@example.com",
                    "current_password": "TempPassw0rd!",
                    "new_password": "BrandNewPass1!",
                },
            )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_subportfolio_idor_returns_404():
    app = FastAPI()
    app.include_router(subport_router, prefix="/api/v1")
    caller = _user(id="attacker")

    mock_db = AsyncMock()

    async def fake_db():
        yield mock_db

    async def fake_email():
        return caller.email

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user_email] = fake_email

    with patch(
        "app.api.v1.endpoints.origination._user",
        new=AsyncMock(return_value=caller),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/sub-portfolios/victim-uuid")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_billing_stub_still_disabled():
    app = FastAPI()
    app.include_router(billing_router, prefix="/api/v1")

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = fake_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/billing/webhook/stub",
            json={"event": "payment_succeeded", "subscription_id": "sub-1"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_confirm_password_otp_locks_after_five_failures():
    from app.services.auth import password_change as pc

    stored = {
        "otp_hash": pc._hash_otp("u1", "111111"),
        "new_password_hash": pc._hash_new_password("u1", "NewSecurePass1!"),
        "token": "tok",
        "attempts": 4,
    }
    with patch("app.services.auth.password_change.cache_get", new=AsyncMock(return_value=stored)):
        with patch("app.services.auth.password_change.cache_set", new=AsyncMock()) as setter:
            with patch("app.services.auth.password_change.cache_delete", new=AsyncMock()) as deleter:
                ok = await pc.confirm_password_change(
                    "u1", code="000000", new_password="NewSecurePass1!"
                )
    assert ok is False
    deleter.assert_awaited_once()
    setter.assert_not_awaited()


def test_decode_token_rejects_alg_none():
    import base64
    import json

    from app.core.security import JWTError, decode_token

    def _b64(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    token = (
        f"{_b64({'alg': 'none', 'typ': 'JWT'})}."
        f"{_b64({'sub': 'a@x.io', 'exp': 4102444800, 'type': 'access'})}."
    )
    with pytest.raises(JWTError):
        decode_token(token)


@pytest.mark.asyncio
async def test_require_admin_uses_db_role_not_jwt_claim(monkeypatch):
    from fastapi import HTTPException

    from app.core.deps import require_admin
    from app.domain.rbac import SystemRole

    async def fake_role(_db, email):
        return _user(email=email, role=UserRole.VIEWER), SystemRole.USER

    monkeypatch.setattr("app.core.rbac_deps.get_user_and_role", fake_role)
    with pytest.raises(HTTPException) as exc:
        await require_admin(email="trial@example.com", db=AsyncMock())
    assert exc.value.status_code == 403
    assert "Admin" in str(exc.value.detail)
