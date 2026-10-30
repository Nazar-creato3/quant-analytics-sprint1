"""Auth /me must reject bad tokens without opening a DB session."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.auth import router as auth_router
from app.core.deps import get_db, get_db_after_auth


@pytest.mark.asyncio
async def test_auth_me_bad_token_fast_no_db():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")

    db_called = False

    async def fail_if_db_opened():
        nonlocal db_called
        db_called = True
        raise AssertionError("get_db_after_auth must not run for invalid JWT")
        yield  # pragma: no cover

    app.dependency_overrides[get_db_after_auth] = fail_if_db_opened
    app.dependency_overrides[get_db] = fail_if_db_opened

    transport = ASGITransport(app=app)
    started = time.perf_counter()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
        )
    elapsed = time.perf_counter() - started

    assert resp.status_code == 401
    assert db_called is False
    assert elapsed < 1.0, f"/auth/me bad token took {elapsed:.2f}s (expected <1s)"


@pytest.mark.asyncio
async def test_auth_me_no_token_fast_no_db():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")

    db_called = False

    async def fail_if_db_opened():
        nonlocal db_called
        db_called = True
        raise AssertionError("get_db_after_auth must not run without Bearer token")
        yield  # pragma: no cover

    app.dependency_overrides[get_db_after_auth] = fail_if_db_opened

    transport = ASGITransport(app=app)
    started = time.perf_counter()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/auth/me")
    elapsed = time.perf_counter() - started

    assert resp.status_code == 401
    assert db_called is False
    assert elapsed < 1.0
