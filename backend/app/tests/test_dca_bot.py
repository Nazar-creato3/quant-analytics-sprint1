"""Tests for standalone DCA bot API."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.dca_bots import _memory_bots, router as dca_router
from app.core.deps import get_current_user_email, get_db


@pytest.fixture(autouse=True)
def clear_memory_bots():
    _memory_bots.clear()
    yield
    _memory_bots.clear()


@pytest.fixture(autouse=True)
def bypass_access():
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
    app.include_router(dca_router, prefix="/api/v1")

    async def fake_user():
        return "test@example.com"

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user_email] = fake_user
    app.dependency_overrides[get_db] = fake_db

    with (
        patch("app.api.v1.endpoints.dca_bots.audit.log", new_callable=AsyncMock),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c


VALID_BODY = {
    "ticker": "AAPL",
    "total_capital": 5000.0,
    "order_size_usd": 500.0,
    "max_entries": 5,
    "interval_ticks": 1,
    "current_price": 180.0,
}


class TestDcaBotApi:
    @patch("app.services.bots.store.cache_set", new_callable=AsyncMock, return_value=False)
    @patch("app.services.bots.store.cache_get", new_callable=AsyncMock, return_value=None)
    def test_create_and_list(self, _get, _set, client):
        resp = client.post("/api/v1/dca", json=VALID_BODY)
        assert resp.status_code == 201
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["bot_id"]

        listed = client.get("/api/v1/dca")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    @patch("app.services.bots.store.cache_set", new_callable=AsyncMock, return_value=False)
    @patch("app.services.bots.store.cache_get", new_callable=AsyncMock, return_value=None)
    def test_manual_tick_increases_entries(self, _get, _set, client):
        create = client.post("/api/v1/dca", json=VALID_BODY)
        bot_id = create.json()["bot_id"]
        detail = client.get(f"/api/v1/dca/{bot_id}")
        before = detail.json()["entries_count"]
        tick = client.post(f"/api/v1/dca/{bot_id}/price?price=175.0")
        assert tick.status_code == 200
        after = client.get(f"/api/v1/dca/{bot_id}").json()["entries_count"]
        assert after >= before


def test_missing_order_size_does_not_buy() -> None:
    from app.services.bots.dca import apply_dca_tick, new_runtime

    data = {
        "config": {"ticker": "AAPL", "total_capital": 5000, "max_entries": 5, "interval_ticks": 1},
        "runtime": new_runtime(180.0),
        "is_active": True,
    }
    out = apply_dca_tick(data, 180.0, bot_id="b1")
    assert float(out["runtime"]["position_qty"]) == 0.0
    assert int(out["runtime"]["entries_count"]) == 0
