"""Tests for GET /watchlists/effective dashboard API."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.watchlist_news import watchlist_router
from app.core.deps import get_current_user_email, get_db


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(watchlist_router, prefix="/api/v1")

    async def fake_user():
        return "user@test.com"

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user_email] = fake_user
    app.dependency_overrides[get_db] = fake_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestEffectiveWatchlistEndpoint:
    @patch(
        "app.services.settings.watchlist.get_effective_watchlist_enriched",
        new_callable=AsyncMock,
        return_value=[
            {
                "symbol": "TSLA",
                "category": "equities",
                "market": "us",
                "sector": None,
                "label": "US equity",
                "label_ru": "US equity",
                "filter_key": "other",
            },
            {
                "symbol": "NVDA",
                "category": "equities",
                "market": "us",
                "sector": "technology",
                "label": "технологии · US equity",
                "label_ru": "технологии · US equity",
                "filter_key": "tech",
            },
        ],
    )
    def test_returns_user_tickers_with_categories(self, _mock_watchlist, client):
        resp = client.get("/api/v1/watchlists/effective")
        assert resp.status_code == 200
        assert resp.json() == {
            "tickers": ["TSLA", "NVDA"],
            "entries": [
                {
                    "symbol": "TSLA",
                    "category": "equities",
                    "market": "us",
                    "sector": None,
                    "label": "US equity",
                    "label_ru": "US equity",
                    "filter_key": "other",
                },
                {
                    "symbol": "NVDA",
                    "category": "equities",
                    "market": "us",
                    "sector": "technology",
                    "label": "технологии · US equity",
                    "label_ru": "технологии · US equity",
                    "filter_key": "tech",
                },
            ],
        }

    def test_returns_full_watchlist_without_truncation(self, client):
        symbols = [f"SYM{i}" for i in range(17)]

        with patch(
            "app.services.settings.watchlist.get_effective_watchlist_enriched",
            new_callable=AsyncMock,
            return_value=[
                {
                    "symbol": symbol,
                    "category": "equities",
                    "market": "us",
                    "sector": None,
                    "label": symbol,
                    "label_ru": symbol,
                    "filter_key": "other",
                }
                for symbol in symbols
            ],
        ):
            resp = client.get("/api/v1/watchlists/effective")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["tickers"]) == 17
        assert body["tickers"] == symbols
        assert len(body["entries"]) == 17
