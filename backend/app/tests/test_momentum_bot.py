"""Tests for standalone momentum bot API and executor."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.momentum_bots import _memory_bots, router as momentum_router
from app.core.deps import get_current_user_email, get_db
from app.services.bots.momentum import apply_momentum_tick, new_runtime


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
    app.include_router(momentum_router, prefix="/api/v1")

    async def fake_user():
        return "test@example.com"

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user_email] = fake_user
    app.dependency_overrides[get_db] = fake_db

    with (
        patch("app.api.v1.endpoints.momentum_bots.audit.log", new_callable=AsyncMock),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c


VALID_BODY = {
    "ticker": "NVDA",
    "total_capital": 10000.0,
    "position_size_pct": 0.5,
    "lookback_ticks": 5,
    "entry_momentum_pct": 0.01,
    "current_price": 100.0,
}


def test_momentum_executor_enters_on_uptrend():
    data = {
        "config": {
            "ticker": "TEST",
            "total_capital": 10_000,
            "position_size_pct": 0.5,
            "lookback_ticks": 5,
            "entry_momentum_pct": 0.01,
            "take_profit_pct": 0.06,
            "stop_loss_pct": 0.04,
            "entry_price": 100.0,
        },
        "runtime": new_runtime(100.0),
        "realized_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
        "is_paused": False,
    }
    for p in [100, 101, 102, 103, 104, 106]:
        data = apply_momentum_tick(data, float(p), bot_id="t1")
    assert float(data["runtime"]["position_qty"]) > 0


class TestMomentumBotApi:
    @patch("app.services.bots.store.cache_set", new_callable=AsyncMock, return_value=False)
    @patch("app.services.bots.store.cache_get", new_callable=AsyncMock, return_value=None)
    def test_create_and_list(self, _get, _set, client):
        resp = client.post("/api/v1/momentum", json=VALID_BODY)
        assert resp.status_code == 201
        assert resp.json()["ticker"] == "NVDA"
        assert len(client.get("/api/v1/momentum").json()) == 1
