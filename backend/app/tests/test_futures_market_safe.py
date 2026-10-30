"""GA16-359: no flag name; ticker required (no silent MIX default)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.futures_market import router
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


def test_flag_off_hides_name(client):
    with patch("app.api.v1.endpoints.futures_market.is_enabled", return_value=False):
        resp = client.get("/api/v1/futures/market", params={"ticker": "Si"})
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "flag" not in detail.lower()
    assert "futures" not in detail.lower()
    assert "qa_futures" not in detail.lower()


def test_ticker_required_no_mix_default(client):
    with patch("app.api.v1.endpoints.futures_market.is_enabled", return_value=True):
        with patch("app.api.v1.endpoints.futures_market.explain_market") as mocked:
            resp = client.get("/api/v1/futures/market")
    assert resp.status_code == 422
    mocked.assert_not_called()
