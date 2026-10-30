"""GA16-358: lookthrough flag-off must not leak flag names."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.fund_lookthrough import router
from app.services.qa.session_user import require_session_user_id


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_session_user_id] = lambda: "u1"
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_lookthrough_flag_off_hides_name(client):
    with patch("app.api.v1.endpoints.fund_lookthrough.is_enabled", return_value=False):
        resp = client.get("/api/v1/portfolio/me/lookthrough")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "lookthrough" not in detail.lower()
    assert "flag" not in detail.lower()
    assert "qa_fund" not in detail.lower()
