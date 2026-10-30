"""Universal Marketstack search — architectural, not a pre-loaded ticker dump."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.market_data.marketstack_catalog import is_data_only_symbol
from app.services.market_data.universe_search import search_universe


@pytest.fixture(autouse=True)
def _no_live_moex_board():
    with patch(
        "app.services.market_data.universe_search._load_moex_board_rows",
        return_value=[("SBER", "Сбербанк России"), ("GAZP", "Газпром")],
    ):
        yield


def _ms_row(symbol: str, name: str, acronym: str, mic: str, country: str) -> dict:
    return {
        "symbol": symbol,
        "name": name,
        "stock_exchange": {
            "acronym": acronym,
            "mic": mic,
            "country_code": country,
        },
    }


TOKYO_NOT_IN_WATCHLIST = _ms_row("9983.T", "Fast Retailing", "TSE", "XTKS", "JP")
FRANKFURT_NOT_IN_WATCHLIST = _ms_row("VOW3.XETRA", "Volkswagen", "XETRA", "XETR", "DE")
HK_NOT_IN_WATCHLIST = _ms_row("3690.HK", "Meituan", "HKEX", "XHKG", "HK")
SHANGHAI_NOT_IN_WATCHLIST = _ms_row("600519.SS", "Kweichow Moutai", "SSE", "XSHG", "CN")
PANASONIC_NOT_IN_WATCHLIST = _ms_row("6752.T", "Panasonic", "TSE", "XTKS", "JP")

_FIVE_FOREIGN = [
    TOKYO_NOT_IN_WATCHLIST,
    FRANKFURT_NOT_IN_WATCHLIST,
    HK_NOT_IN_WATCHLIST,
    SHANGHAI_NOT_IN_WATCHLIST,
    PANASONIC_NOT_IN_WATCHLIST,
]


@pytest.mark.asyncio
async def test_search_returns_instruments_absent_from_watchlist():
    async def fake_search(self, query: str, *, limit: int = 15):  # noqa: ARG001
        return list(_FIVE_FOREIGN)

    with patch(
        "app.services.market_data.http_providers.MarketStackClient.search_tickers",
        fake_search,
    ), patch(
        "app.services.market_data.universe_search.key_configured",
        return_value=True,
    ):
        hits = await search_universe("retail", limit=10, pinned_symbols=["AAPL", "MSFT", "SBER"])

    symbols = {h.symbol for h in hits}
    for row in _FIVE_FOREIGN:
        assert row["symbol"] in symbols
        assert row["symbol"] not in {"AAPL", "MSFT", "SBER"}
    assert all(h.data_tier == "data_only" for h in hits if h.symbol.endswith((".T", ".HK", ".XETRA", ".SS")))
    assert all(h.data_tier_label_ru == "Только котировки" for h in hits if h.data_tier == "data_only")
    assert all(h.pinned is False for h in hits if h.symbol.endswith(".T"))


@pytest.mark.asyncio
async def test_search_matches_company_name_and_ticker():
    with patch(
        "app.services.market_data.universe_search.key_configured",
        return_value=False,
    ):
        by_name = await search_universe("Apple", limit=20, pinned_symbols=[])
        by_ru = await search_universe("Сбер", limit=20, pinned_symbols=[])
        by_ticker = await search_universe("AAPL", limit=20, pinned_symbols=[])

    assert any(h.symbol == "AAPL" for h in by_name)
    assert any(h.symbol == "SBER" for h in by_ru)
    assert any(h.symbol == "AAPL" for h in by_ticker)


@pytest.mark.asyncio
async def test_search_is_not_limited_to_pinned_watchlist():
    async def fake_search(self, query: str, *, limit: int = 15):  # noqa: ARG001
        return [_ms_row("7203.T", "Toyota Motor", "TSE", "XTKS", "JP")]

    with patch(
        "app.services.market_data.http_providers.MarketStackClient.search_tickers",
        fake_search,
    ), patch(
        "app.services.market_data.universe_search.key_configured",
        return_value=True,
    ):
        hits = await search_universe("7203", pinned_symbols=["AAPL"])

    assert any(h.symbol == "7203.T" for h in hits)
    assert all(h.symbol != "AAPL" or h.source == "alpaca" for h in hits)


@pytest.mark.asyncio
async def test_search_us_equity_is_full_trading_tier():
    async def fake_search(self, query: str, *, limit: int = 15):  # noqa: ARG001
        return [_ms_row("MSFT", "Microsoft", "NASDAQ", "XNAS", "US")]

    with patch(
        "app.services.market_data.http_providers.MarketStackClient.search_tickers",
        fake_search,
    ), patch(
        "app.services.market_data.universe_search.key_configured",
        return_value=True,
    ):
        hits = await search_universe("MSFT", limit=8, pinned_symbols=[])

    msft = next(h for h in hits if h.symbol == "MSFT")
    assert msft.data_tier == "full_trading"
    assert msft.data_tier_label_ru == "К торговле"


@pytest.mark.asyncio
async def test_search_category_filter_fx_excludes_equities():
    hits = await search_universe("EUR", category="fx", pinned_symbols=[])
    assert hits
    assert all(h.category == "fx" for h in hits)
    assert all(h.data_tier == "data_only" for h in hits)


def test_suffix_only_tokyo_name_is_data_only_without_catalog_membership():
    assert is_data_only_symbol("9983.T")
    assert is_data_only_symbol("600519.SS")
    assert not is_data_only_symbol("AAPL")


def test_search_endpoint_returns_universe_not_watchlist():
    from datetime import datetime, timezone

    from app.api.v1.endpoints.market import market_router
    from app.core.deps import get_current_user_email, get_db
    from app.db.models import User, UserRole

    app = FastAPI()
    app.include_router(market_router, prefix="/api/v1")

    async def fake_user():
        return "trader@test.com"

    user = User(
        id="u-test",
        email="trader@test.com",
        hashed_password="x",
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    async def fake_db():
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=user))
        yield db

    app.dependency_overrides[get_current_user_email] = fake_user
    app.dependency_overrides[get_db] = fake_db

    async def fake_search(query, *, limit=10, category="all", region="all", pinned_symbols=None):
        from app.services.market_data.universe_search import UniverseHit

        assert "AAPL" in (pinned_symbols or [])
        return [
            UniverseHit(
                symbol="9983.T",
                name="Fast Retailing",
                exchange="TSE",
                region="asia",
                category="equities",
                category_label_ru="Акции",
                data_tier="data_only",
                data_tier_label_ru="Только котировки",
                source="marketstack",
                pinned=False,
            )
        ]

    with patch(
        "app.services.settings.watchlist.get_effective_watchlist",
        AsyncMock(return_value=["AAPL"]),
    ), patch(
        "app.services.market_data.universe_search.search_universe",
        fake_search,
    ), TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/market/search", params={"q": "9983"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["watchlist_is_pins_only"] is True
    assert body["items"][0]["symbol"] == "9983.T"
    assert body["items"][0]["data_tier_label_ru"] == "Только котировки"
    assert body["items"][0]["pinned"] is False
