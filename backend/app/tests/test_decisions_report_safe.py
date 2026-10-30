"""GA16-357: decisions API must not expose flag names or str(exc)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.decisions_report import router
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


def test_flag_off_hides_internal_name(client):
    with patch("app.api.v1.endpoints.decisions_report.is_enabled", return_value=False):
        resp = client.get("/api/v1/portfolio/me/decisions")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "59" not in detail
    assert "flag" not in detail.lower()
    assert "qa_59" not in detail


def test_exception_hides_str_exc(client):
    with (
        patch("app.api.v1.endpoints.decisions_report.is_enabled", return_value=True),
        patch(
            "app.api.v1.endpoints.decisions_report.analyze_decisions",
            side_effect=RuntimeError("secret_formula_xyz boom"),
        ),
    ):
        resp = client.get("/api/v1/portfolio/me/decisions")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "secret_formula_xyz" not in detail
    assert "Не удалось" in detail
