"""GA16-324: /terminal/news without symbols must not invent AAPL/MSFT/NVDA."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.terminal import router as terminal_router
from app.services.terminal_platform.models import FetchResult


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(terminal_router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_ga16_324_provider_news_without_symbols_passes_none(client):
    captured: dict = {}

    async def _get_news(*, symbols=None, limit=20, preferred_provider=None):
        captured["symbols"] = symbols
        return FetchResult(success=True, data=[], provider=preferred_provider or "test", metadata={})

    router = MagicMock()
    router.get_news = AsyncMock(side_effect=_get_news)

    with patch("app.api.v1.endpoints.terminal.get_terminal_router", return_value=router):
        resp = client.get("/api/v1/terminal/news", params={"provider": "alpha_vantage", "limit": 5})

    assert resp.status_code == 200
    assert captured["symbols"] is None
    assert "AAPL" not in str(captured)
