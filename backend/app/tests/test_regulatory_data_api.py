"""API tests for /regulatory endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.regulatory_data import router
from app.services.fundamental_data.models import RegulatoryDataResult
from app.services.qa.session_user import require_session_user_id


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_session_user_id] = lambda: "reg-user"
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def open_client():
    """Client without session override — proves auth gate."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


class TestRegulatoryDataAPI:
    def test_status_requires_session(self, open_client):
        resp = open_client.get("/api/v1/regulatory/status")
        assert resp.status_code in (401, 403, 422)

    def test_sec_filings_requires_session(self, open_client):
        resp = open_client.get("/api/v1/regulatory/sec-filings/AAPL")
        assert resp.status_code in (401, 403, 422)

    def test_status_disabled(self, client):
        with patch(
            "app.api.v1.endpoints.regulatory_data.get_fundamental_data_provider"
        ) as mock_factory:
            mock_provider = AsyncMock()
            mock_provider.source_enabled = False
            mock_factory.return_value = mock_provider
            resp = client.get("/api/v1/regulatory/status")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_sec_filings_disabled(self, client):
        disabled = RegulatoryDataResult(
            success=False,
            error="Регуляторные данные временно недоступны",
            error_code="SOURCE_DISABLED",
            source_enabled=False,
        )
        with patch(
            "app.api.v1.endpoints.regulatory_data.get_fundamental_data_provider"
        ) as mock_factory:
            mock_provider = AsyncMock()
            mock_provider.get_sec_filings = AsyncMock(return_value=disabled)
            mock_factory.return_value = mock_provider
            resp = client.get("/api/v1/regulatory/sec-filings/AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "SOURCE_DISABLED"
        assert "openbb" not in resp.text.lower()

    def test_finra_short_interest_success(self, client):
        ok = RegulatoryDataResult(
            success=True,
            data={"symbol": "AAPL", "records": [], "count": 0},
            source_enabled=True,
        )
        with patch(
            "app.api.v1.endpoints.regulatory_data.get_fundamental_data_provider"
        ) as mock_factory:
            mock_provider = AsyncMock()
            mock_provider.get_finra_short_interest = AsyncMock(return_value=ok)
            mock_factory.return_value = mock_provider
            resp = client.get("/api/v1/regulatory/finra-short-interest/AAPL")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "openbb" not in resp.text.lower()
