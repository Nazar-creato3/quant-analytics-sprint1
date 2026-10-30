"""Classic forex is data-only: searchable quotes, no execution path."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.instrument.data_only import (
    DataOnlyInstrumentError,
    assert_execution_allowed,
    execution_flags,
    is_data_only_symbol,
)
from app.services.market_data.forex_catalog import (
    FOREX_FEED_LABEL_RU,
    FOREX_PROVIDER_CHOICE,
    FOREX_PROVIDER_NAME,
    canonical_forex_symbol,
    is_forex_pair,
    match_forex_catalog,
)
from app.services.market_data.universe_search import search_universe
from app.services.terminal_platform.providers.forex import ForexDataProvider


def test_twelve_data_chosen_over_finnhub_for_free_tier_forex():
    assert FOREX_PROVIDER_NAME == "twelvedata"
    assert "Twelve Data" in FOREX_PROVIDER_CHOICE
    assert "Finnhub" in FOREX_PROVIDER_CHOICE


def test_forex_canonical_and_detection():
    assert canonical_forex_symbol("EURUSD") == "EUR/USD"
    assert canonical_forex_symbol("eur-usd") == "EUR/USD"
    assert is_forex_pair("GBP/JPY")
    assert is_forex_pair("USDJPY")
    assert not is_forex_pair("AAPL")
    assert not is_forex_pair("BTC-USD")
    assert not is_forex_pair("USD000UTSTOM")


def test_forex_pairs_are_data_only():
    assert is_data_only_symbol("EUR/USD")
    assert is_data_only_symbol("GBPJPY")
    flags = execution_flags("EUR/USD")
    assert flags["data_only"] is True
    assert flags["execution_enabled"] is False
    assert flags["feed"] == "forex"
    assert flags["feed_label_ru"] == FOREX_FEED_LABEL_RU
    with pytest.raises(DataOnlyInstrumentError) as exc:
        assert_execution_allowed("EUR/USD")
    assert "EUR/USD" in str(exc.value)
    assert FOREX_FEED_LABEL_RU in str(exc.value)


@pytest.mark.asyncio
async def test_forex_searchable_under_currencies_category():
    hits = await search_universe("EUR/USD", category="fx")
    assert any(h.symbol == "EUR/USD" for h in hits)
    hit = next(h for h in hits if h.symbol == "EUR/USD")
    assert hit.category_label_ru == "Валюты"
    assert hit.data_tier == "data_only"
    majors = {p.symbol for p in match_forex_catalog("USD", limit=20)}
    assert "EUR/USD" in majors
    assert "GBP/USD" in majors
    assert "USD/JPY" in majors
    assert "USD/CNY" in majors


@pytest.mark.asyncio
async def test_forex_provider_quote_and_rejects_equities():
    provider = ForexDataProvider()
    provider._api_key = "test-key"
    equity = await provider.fetch_quote("AAPL")
    assert equity.success is False
    assert equity.error_code == "UNSUPPORTED"

    mock_client = AsyncMock()
    mock_client.get_latest_quote = AsyncMock(
        return_value={
            "ticker": "EUR/USD",
            "price": 1.085,
            "bid": 1.0849,
            "ask": 1.0851,
            "change_pct": 0.12,
            "timestamp": "2026-08-19T12:00:00Z",
            "source": "twelvedata",
        }
    )
    with patch.object(provider, "_client", return_value=mock_client):
        result = await provider.fetch_quote("EURUSD")
    assert result.success is True
    assert result.data.price == Decimal("1.085")
    assert result.metadata.get("data_only") is True
    assert result.metadata.get("execution_enabled") is False
    assert result.metadata.get("backend") == "twelvedata"


@pytest.mark.asyncio
async def test_submit_manual_order_rejects_forex():
    from app.schemas.orders import ManualOrderCreate
    from app.services.orders.service import submit_manual_order

    body = ManualOrderCreate(
        ticker="EUR/USD",
        side="buy",
        order_type="limit",
        quantity=1000,
        limit_price=1.08,
    )
    with pytest.raises(DataOnlyInstrumentError):
        await submit_manual_order(
            AsyncMock(),
            body,
            user_id="u1",
            user_email="test@example.com",
        )


def test_post_order_api_rejects_forex_pair():
    from app.api.v1.endpoints.orders import router as orders_router
    from app.core.deps import get_current_user_email, get_user_db
    from app.db.models import User, UserRole

    app = FastAPI()
    app.include_router(orders_router, prefix="/api/v1")

    async def fake_user():
        return "trader@test.com"

    user = User(
        id="u-fx",
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
    app.dependency_overrides[get_user_db] = fake_db

    expected = f"EUR/USD: только данные — торговля недоступна ({FOREX_FEED_LABEL_RU})"
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/v1/orders",
            json={
                "ticker": "EUR/USD",
                "side": "buy",
                "order_type": "limit",
                "quantity": 1000,
                "limit_price": 1.08,
            },
        )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "По этой бумаге заявку разместить нельзя."}
    assert expected  # internal reason still built for the log, not shown to the user


def test_symbol_rules_forex_has_no_execution():
    from app.api.v1.endpoints.orders import router as orders_router
    from app.core.deps import get_current_user_email, get_user_db

    app = FastAPI()
    app.include_router(orders_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_email] = lambda: "trader@test.com"
    app.dependency_overrides[get_user_db] = lambda: AsyncMock()

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/orders/symbol-rules/EURUSD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_only"] is True
    assert body["execution_enabled"] is False
    assert body["venue"] == "forex_data"
