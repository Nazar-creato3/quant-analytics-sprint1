"""Tests for GET /direct-deals/symbols."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.direct_deals import router
from app.core.deps import get_current_user_email, get_db


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def fake_user():
        return "user@test.com"

    async def fake_db():
        db = AsyncMock()
        db.execute.return_value = _ExecuteResult(
            [
                SimpleNamespace(
                    symbol="FCX",
                    source="finam",
                    instrument_type="stock",
                    tradable_unit="per_share",
                    metadata_={"name": "Freeport-McMoRan", "exchange": "NYSE"},
                )
            ]
        )
        yield db

    app.dependency_overrides[get_current_user_email] = fake_user
    app.dependency_overrides[get_db] = fake_db

    async def _skip_hints(symbols):  # noqa: ARG001
        return None

    with patch(
        "app.api.v1.endpoints.direct_deals._apply_execution_hints",
        new=_skip_hints,
    ), TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestDirectDealsSymbolsEndpoint:
    @patch(
        "app.api.v1.endpoints.direct_deals.get_effective_watchlist",
        new_callable=AsyncMock,
        return_value=["ETHUSDT", "XLE"],
    )
    def test_returns_merged_tradable_universe(self, _mock_watchlist, client):
        resp = client.get("/api/v1/direct-deals/symbols")

        assert resp.status_code == 200
        body = resp.json()
        symbols = {row["symbol"]: row for row in body}

        assert "BTCUSDT" in symbols
        assert symbols["ETHUSDT"]["asset_class"] == "crypto"
        assert symbols["XLE"]["exchange"] == "US"
        assert symbols["XLE"]["asset_class"] == "etf"
        assert symbols["FCX"]["name"] == "Freeport-McMoRan"
        assert symbols["FCX"]["exchange"] == "NYSE"

    @patch(
        "app.api.v1.endpoints.direct_deals.search_universe",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch(
        "app.api.v1.endpoints.direct_deals.get_effective_watchlist",
        new_callable=AsyncMock,
        return_value=[],
    )
    def test_filters_by_query(self, _mock_watchlist, _mock_search, client):
        resp = client.get("/api/v1/direct-deals/symbols?q=freeport")

        assert resp.status_code == 200
        body = resp.json()
        assert [row["symbol"] for row in body] == ["FCX"]

    @patch(
        "app.api.v1.endpoints.direct_deals.get_effective_watchlist",
        new_callable=AsyncMock,
        return_value=["AAPL"],
    )
    def test_query_merges_universe_name_hits(self, _mock_watchlist, client):
        from app.services.market_data.universe_search import UniverseHit

        hit = UniverseHit(
            symbol="7203.T",
            name="Toyota Motor",
            exchange="TSE",
            region="asia",
            category="equities",
            category_label_ru="Акции",
            data_tier="data_only",
            data_tier_label_ru="Только котировки",
            source="marketstack",
        )
        with patch(
            "app.api.v1.endpoints.direct_deals.search_universe",
            new_callable=AsyncMock,
            return_value=[hit],
        ):
            resp = client.get("/api/v1/direct-deals/symbols?q=toyota")

        assert resp.status_code == 200
        symbols = {row["symbol"] for row in resp.json()}
        assert "7203.T" in symbols
