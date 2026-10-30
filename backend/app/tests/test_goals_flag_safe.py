"""GA16-361: goals flag-off must not leak flag names."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.goals import router
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


def test_goals_flag_off_hides_name(client):
    with patch("app.api.v1.endpoints.goals.is_enabled", return_value=False):
        resp = client.post(
            "/api/v1/goals",
            json={"target_amount": 1000, "target_date": "2030-01-01"},
        )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "goals" not in detail.lower()
    assert "flag" not in detail.lower()
    assert "qa_goals" not in detail.lower()
