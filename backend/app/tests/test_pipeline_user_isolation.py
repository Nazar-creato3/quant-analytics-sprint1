"""API-level pipeline report isolation between users."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.pipeline import router as pipeline_router
from app.core.deps import get_current_user_email, get_db, get_user_db
from app.db.models import User, UserRole


def _user(user_id: str, email: str) -> User:
    return User(
        id=user_id,
        email=email,
        hashed_password="x",
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def pipeline_client():
    app = FastAPI()
    app.include_router(pipeline_router, prefix="/api/v1")

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = fake_db

    app.dependency_overrides[get_user_db] = fake_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_get_foreign_report_returns_404(pipeline_client):
    mock_db = AsyncMock()
    alice = _user("user-a", "alice@test.com")

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = alice

    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None

    mock_db.execute = AsyncMock(side_effect=[user_result, empty_result])

    async def fake_db():
        yield mock_db

    pipeline_client.app.dependency_overrides[get_db] = fake_db

    pipeline_client.app.dependency_overrides[get_user_db] = fake_db
    pipeline_client.app.dependency_overrides[get_current_user_email] = lambda: "alice@test.com"

    resp = pipeline_client.get("/api/v1/pipeline/reports/report-owned-by-bob")
    assert resp.status_code == 404


def test_pipeline_status_ignores_foreign_run_report(pipeline_client):
    """User cannot recover another user's pipeline run via status endpoint."""
    mock_db = AsyncMock()
    alice = _user("user-a", "alice@test.com")

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = alice

    empty_report = MagicMock()
    empty_report.scalar_one_or_none.return_value = None

    mock_db.execute = AsyncMock(side_effect=[user_result, empty_report])

    async def fake_db():
        yield mock_db

    pipeline_client.app.dependency_overrides[get_db] = fake_db

    pipeline_client.app.dependency_overrides[get_user_db] = fake_db
    pipeline_client.app.dependency_overrides[get_current_user_email] = lambda: "alice@test.com"

    resp = pipeline_client.get("/api/v1/pipeline/status/foreign-run-id")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in {"unknown", "failed", "pending", "started", "progress"}
    assert body.get("report_id") is None
