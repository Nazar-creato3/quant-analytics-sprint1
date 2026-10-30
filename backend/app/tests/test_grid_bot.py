"""Tests for grid bot API endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.grid import _memory_bots, router as grid_router
from app.core.deps import get_current_user_email, get_db


@pytest.fixture(autouse=True)
def clear_memory_bots():
    _memory_bots.clear()
    yield
    _memory_bots.clear()


@pytest.fixture(autouse=True)
def bypass_grid_access():
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.role = "admin"
    with patch(
        "app.core.access_deps.require_access_action",
        new_callable=AsyncMock,
        return_value=mock_user,
    ):
        yield


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(grid_router, prefix="/api/v1")

    async def fake_user():
        return "test@example.com"

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user_email] = fake_user
    app.dependency_overrides[get_db] = fake_db

    with (
        patch("app.api.v1.endpoints.grid.audit.log", new_callable=AsyncMock),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c


VALID_BODY = {
    "ticker": "AAPL",
    "lower_price": 170.0,
    "upper_price": 200.0,
    "grid_count": 10,
    "total_capital": 10000.0,
    "current_price": 182.5,
}


class TestGridBotCreate:
    @patch("app.api.v1.endpoints.grid.cache_set", new_callable=AsyncMock, return_value=False)
    @patch("app.api.v1.endpoints.grid.cache_get", new_callable=AsyncMock, return_value=None)
    def test_create_without_redis_uses_memory(self, _get, _set, client):
        resp = client.post("/api/v1/grid", json=VALID_BODY)
        assert resp.status_code == 201
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["bot_id"]
        assert data["lower_price"] == 170.0
        assert data["upper_price"] == 200.0

        list_resp = client.get("/api/v1/grid")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

    def test_create_rejects_invalid_range(self, client):
        body = {**VALID_BODY, "lower_price": 200.0, "upper_price": 170.0}
        resp = client.post("/api/v1/grid", json=body)
        assert resp.status_code == 400

    def test_create_requires_auth_fields(self, client):
        resp = client.post("/api/v1/grid", json={"ticker": "AAPL"})
        assert resp.status_code == 422


class TestGridSuggest:
    @patch("app.services.market_data.client.get_grid_tick_quote", new_callable=AsyncMock)
    def test_suggest_returns_bounds(self, mock_quote, client):
        mock_quote.return_value = {"ticker": "AAPL", "price": 200.0, "source": "yfinance"}

        resp = client.get("/api/v1/grid/suggest/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["current_price"] == 200.0
        assert data["lower_price"] < data["current_price"] < data["upper_price"]


class TestGridBotActivity:
    @patch("app.api.v1.endpoints.grid.cache_set", new_callable=AsyncMock, return_value=False)
    @patch("app.api.v1.endpoints.grid.cache_get", new_callable=AsyncMock, return_value=None)
    @patch(
        "app.services.market_data.client.get_grid_tick_quote",
        new_callable=AsyncMock,
        return_value={"ticker": "AAPL", "price": 182.5, "source": "test"},
    )
    def test_activity_endpoint_returns_events(self, _quote, _get, _set, client):
        create = client.post("/api/v1/grid", json=VALID_BODY)
        assert create.status_code == 201
        bot_id = create.json()["bot_id"]

        resp = client.get(f"/api/v1/grid/bots/{bot_id}/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bot_id"] == bot_id
        assert data["ticker"] == "AAPL"
        assert len(data["recent_events"]) >= 1
        assert data["recent_events"][0]["type"] == "created"
        assert data["last_activity_at"]

    def test_activity_not_found(self, client):
        resp = client.get("/api/v1/grid/bots/nonexistent/activity")
        assert resp.status_code == 404

    @patch("app.api.v1.endpoints.grid.cache_set", new_callable=AsyncMock, return_value=False)
    @patch("app.api.v1.endpoints.grid.cache_get", new_callable=AsyncMock, return_value=None)
    @patch(
        "app.services.market_data.client.get_grid_tick_quote",
        new_callable=AsyncMock,
        return_value={"ticker": "AAPL", "price": 182.5, "source": "test"},
    )
    def test_patch_grid_count_before_trades(self, _quote, _get, _set, client):
        create = client.post("/api/v1/grid", json=VALID_BODY)
        assert create.status_code == 201
        bot_id = create.json()["bot_id"]

        patch = client.patch(f"/api/v1/grid/{bot_id}", json={"grid_count": 15})
        assert patch.status_code == 200
        assert patch.json()["grid_count"] == 15

    @patch("app.api.v1.endpoints.grid.cache_set", new_callable=AsyncMock, return_value=False)
    @patch("app.api.v1.endpoints.grid.cache_get", new_callable=AsyncMock, return_value=None)
    @patch(
        "app.services.market_data.client.get_grid_tick_quote",
        new_callable=AsyncMock,
        return_value={"ticker": "AAPL", "price": 182.5, "source": "test"},
    )
    def test_price_tick_records_paper_trades(self, _quote, _get, _set, client):
        create = client.post("/api/v1/grid", json=VALID_BODY)
        bot_id = create.json()["bot_id"]

        tick = client.post(f"/api/v1/grid/{bot_id}/price", params={"price": 175.0})
        assert tick.status_code == 200
        assert tick.json()["last_activity_at"]

        activity = client.get(f"/api/v1/grid/bots/{bot_id}/activity").json()
        if activity["filled_orders"] > 0:
            assert len(activity.get("paper_trades", [])) >= 1
        assert activity.get("open_positions") is not None
        event_types = [e["type"] for e in activity["recent_events"]]
        assert "tick" in event_types
        assert len(activity["pnl_snapshots"]) >= 2

    @patch("app.api.v1.endpoints.grid.cache_set", new_callable=AsyncMock, return_value=False)
    @patch("app.api.v1.endpoints.grid.cache_get", new_callable=AsyncMock, return_value=None)
    @patch(
        "app.services.market_data.client.get_grid_tick_quote",
        new_callable=AsyncMock,
        return_value={"ticker": "AAPL", "price": 182.5, "source": "test"},
    )
    def test_pause_resume_blocks_fills(self, _quote, _get, _set, client):
        create = client.post("/api/v1/grid", json=VALID_BODY)
        bot_id = create.json()["bot_id"]

        pause = client.post(f"/api/v1/grid/{bot_id}/pause")
        assert pause.status_code == 200
        assert pause.json()["is_paused"] is True

        tick = client.post(f"/api/v1/grid/{bot_id}/price", params={"price": 175.0})
        assert tick.status_code == 200
        assert tick.json()["total_trades"] == 0

        resume = client.post(f"/api/v1/grid/{bot_id}/resume")
        assert resume.status_code == 200
        assert resume.json()["is_paused"] is False

        tick2 = client.post(f"/api/v1/grid/{bot_id}/price", params={"price": 174.0})
        assert tick2.status_code == 200
        activity = client.get(f"/api/v1/grid/bots/{bot_id}/activity").json()
        event_types = [e["type"] for e in activity["recent_events"]]
        assert "paused" in event_types
        assert "resumed" in event_types

    @patch("app.api.v1.endpoints.grid.cache_set", new_callable=AsyncMock, return_value=False)
    @patch("app.api.v1.endpoints.grid.cache_get", new_callable=AsyncMock, return_value=None)
    @patch(
        "app.services.market_data.client.get_grid_tick_quote",
        new_callable=AsyncMock,
        return_value={"ticker": "AAPL", "price": 182.5, "source": "test"},
    )
    def test_soft_stop_sets_inactive(self, _quote, _get, _set, client):
        create = client.post("/api/v1/grid", json=VALID_BODY)
        bot_id = create.json()["bot_id"]

        stop = client.post(f"/api/v1/grid/{bot_id}/stop")
        assert stop.status_code == 200
        assert stop.json()["is_active"] is False

        still = client.get(f"/api/v1/grid/{bot_id}")
        assert still.status_code == 200

        tick = client.post(f"/api/v1/grid/{bot_id}/price", params={"price": 170.0})
        assert tick.status_code == 200
        assert tick.json()["total_trades"] == 0

    @patch("app.api.v1.endpoints.grid.cache_set", new_callable=AsyncMock, return_value=False)
    @patch("app.api.v1.endpoints.grid.cache_get", new_callable=AsyncMock, return_value=None)
    @patch(
        "app.services.market_data.client.get_grid_tick_quote",
        new_callable=AsyncMock,
        return_value={"ticker": "AAPL", "price": 182.5, "source": "test"},
    )
    def test_activity_includes_all_grid_levels(self, _quote, _get, _set, client):
        create = client.post("/api/v1/grid", json=VALID_BODY)
        bot_id = create.json()["bot_id"]
        activity = client.get(f"/api/v1/grid/bots/{bot_id}/activity").json()
        assert len(activity["grid_levels"]) >= 2
        assert activity["total_capital"] == 10000.0
