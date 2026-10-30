"""GA16-351: ops observe is ops-only and hides flag/otel fields."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ops_observe as ep
from app.core.access_deps import require_ops_read
from app.core.deps import get_current_user_email, get_db
from app.services.qa.session_user import require_session_user_id


async def _fake_db():
    yield AsyncMock()


@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(ep.router, prefix="/api/v1")
    application.dependency_overrides[get_db] = _fake_db
    application.dependency_overrides[get_current_user_email] = lambda: "ops@example.com"
    application.dependency_overrides[require_session_user_id] = lambda: "ops-user"
    return application


def test_observe_forbidden_for_non_ops(app):
    async def _deny():
        raise HTTPException(status_code=403, detail="ops.read required")

    app.dependency_overrides[require_ops_read] = _deny
    client = TestClient(app)
    resp = client.get("/api/v1/ops/observe")
    assert resp.status_code == 403


def test_observe_hides_live_and_otel(app):
    app.dependency_overrides[require_ops_read] = lambda: MagicMock(id="1")
    client = TestClient(app)
    raw = {
        "status": "on",
        "live": True,
        "partners": True,
        "otel": {"sdk": "on", "exporter": "http://otel:4317"},
        "slo": {"api": "ok"},
    }
    with patch("app.api.v1.endpoints.ops_observe.admin_view", return_value=raw):
        resp = client.get("/api/v1/ops/observe")
    assert resp.status_code == 200
    body = resp.json()
    blob = str(body).lower()
    assert "live" not in body
    assert "partners" not in body
    assert "otel" not in body
    assert "qa_act_live" not in blob
    assert body["slo"]["api"] == "ok"
