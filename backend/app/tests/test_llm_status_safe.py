"""GA16-350: llm-status must not leak flag/vendor/reason codes to the client."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ops as ops_ep
from app.core.deps import get_current_user_email, get_db


async def _fake_db():
    yield AsyncMock()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(ops_ep.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_email] = lambda: "u@example.com"
    app.dependency_overrides[get_db] = _fake_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_llm_status_disabled_hides_internals(client):
    settings = SimpleNamespace(LLM_ENABLED=False, AITUNNEL_API_KEY="x")

    async def _deny_role(*_a, **_k):
        raise HTTPException(status_code=403, detail="denied")

    with (
        patch("app.core.config.get_settings", return_value=settings),
        patch("app.core.rbac_deps.get_user_and_role", new=_deny_role),
    ):
        resp = client.get("/api/v1/ops/llm-status")

    assert resp.status_code == 200
    body = resp.json()
    blob = str(body)
    assert body["available"] is False
    assert body.get("reason") is None
    assert "LLM_ENABLED" not in blob
    assert "AITunnel" not in blob
    assert "aitunnel" not in blob.lower()
    assert "llm_disabled" not in blob
