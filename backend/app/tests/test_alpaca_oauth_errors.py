"""GA16-339: OAuth token errors must not echo provider body to the client."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import trading_accounts as ta
from app.core.deps import get_user_db


async def _fake_db():
    yield AsyncMock()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(ta.router, prefix="/api/v1")
    app.dependency_overrides[get_user_db] = _fake_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_oauth_callback_hides_provider_body(client):
    state = "st-ga16-339"
    ta._oauth_states[state] = {"user_id": "u1", "account_mode": "paper"}

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = '{"error":"invalid_grant","error_description":"secret leak xyz"}'

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    fake_settings = SimpleNamespace(
        ALPACA_OAUTH_CLIENT_ID="cid",
        ALPACA_OAUTH_CLIENT_SECRET="sec",
        ALPACA_OAUTH_REDIRECT_URI="http://cb",
    )

    with (
        patch("app.api.v1.endpoints.trading_accounts.httpx.AsyncClient", return_value=mock_client),
        patch("app.api.v1.endpoints.trading_accounts.settings", fake_settings),
    ):
        resp = client.get(f"/api/v1/trading-accounts/alpaca/callback?code=c&state={state}")

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "secret leak" not in detail
    assert "invalid_grant" not in detail
    assert "Alpaca" not in detail
    assert "Не удалось" in detail
