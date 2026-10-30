"""Minimal tests for portfolio metrics endpoint."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.portfolio import router as portfolio_router
from app.schemas.portfolio import PortfolioMetricsOut

REQUIRED_KEYS = {
    "trading_usd",
    "balance_usd",
    "total_usd",
    "currency",
    "mode",
    "source",
    "open_maneuvers",
    "active_grid_bots",
    "as_of",
}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(portfolio_router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestPortfolioMetricsSchema:
    def test_schema_keys(self):
        payload = PortfolioMetricsOut(
            trading_usd=1000.0,
            balance_usd=10.0,
            total_usd=1010.0,
            mode="paper",
            source="internal",
            as_of="2026-07-12T00:00:00+00:00",
        )
        data = payload.model_dump()
        assert REQUIRED_KEYS.issubset(data.keys())
        assert data["total_usd"] == data["trading_usd"] + data["balance_usd"]

    def test_metrics_endpoint_requires_auth(self, client):
        resp = client.get("/api/v1/portfolio/metrics")
        assert resp.status_code in (401, 403, 422)

    def test_refresh_endpoint_requires_auth(self, client):
        resp = client.post("/api/v1/portfolio/refresh")
        assert resp.status_code in (401, 403, 422)
