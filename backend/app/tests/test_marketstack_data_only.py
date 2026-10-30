"""Tests for Marketstack Asia/Europe data-only coverage."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.services.instrument.data_only import (
    DataOnlyInstrumentError,
    assert_execution_allowed,
    execution_flags,
)
from app.services.market_data.marketstack_catalog import (
    EOD_FEED_LABEL_RU,
    MARKETSTACK_CATALOG,
    MARKETSTACK_WATCHLIST_SEED,
    canonicalize_international_symbol,
    is_data_only_symbol,
    is_marketstack_catalog_symbol,
    lookup_marketstack_instrument,
)
from app.services.terminal_platform.providers.marketstack import MarketstackProvider


def test_marketstack_catalog_covers_asia_europe_blue_chips():
    exchanges = {inst.exchange for inst in MARKETSTACK_CATALOG}
    assert "TSE" in exchanges
    assert "HKEX" in exchanges
    assert "XETRA" in exchanges
    assert "LSE" in exchanges
    assert len(MARKETSTACK_CATALOG) == 23
    assert len(MARKETSTACK_WATCHLIST_SEED) == 23
    assert lookup_marketstack_instrument("005930").symbol == "005930.KS"
    assert lookup_marketstack_instrument("0700").symbol == "0700.HK"
    assert lookup_marketstack_instrument("005930").currency == "KRW"


def test_data_only_flags_for_catalog_symbols():
    assert is_data_only_symbol("7203.T")
    assert is_data_only_symbol("0700.HK")
    assert is_data_only_symbol("SAP.XETRA")
    assert is_data_only_symbol("BARC.L")
    assert not is_data_only_symbol("AAPL")
    flags = execution_flags("7203.T")
    assert flags["data_only"] is True
    assert flags["execution_enabled"] is False
    assert flags["feed"] == "eod"
    assert flags["feed_label_ru"] == EOD_FEED_LABEL_RU


def test_assert_execution_allowed_rejects_data_only():
    with pytest.raises(DataOnlyInstrumentError):
        assert_execution_allowed("7203.T")


@pytest.mark.asyncio
async def test_marketstack_provider_unsupported_for_us_symbol():
    provider = MarketstackProvider()
    provider._api_key = "test-key"
    result = await provider.fetch_quote("AAPL")
    assert result.success is False
    assert result.error_code == "UNSUPPORTED"


@pytest.mark.asyncio
async def test_marketstack_provider_quote_for_catalog_symbol():
    provider = MarketstackProvider()
    provider._api_key = "test-key"
    mock_client = AsyncMock()
    mock_client.get_latest_quote = AsyncMock(
        return_value={
            "ticker": "7203.T",
            "price": 2500.0,
            "timestamp": "2026-08-08T00:00:00+0000",
            "source": "marketstack",
        }
    )
    with patch.object(provider, "_client", return_value=mock_client):
        result = await provider.fetch_quote("7203.T")
    assert result.success is True
    assert result.data.price == Decimal("2500.0")
    assert result.metadata.get("feed") == "eod"
    assert result.metadata.get("data_only") is True


@pytest.mark.asyncio
async def test_submit_manual_order_rejects_data_only():
    from app.schemas.orders import ManualOrderCreate
    from app.services.orders.service import submit_manual_order

    body = ManualOrderCreate(
        ticker="7203.T",
        side="buy",
        order_type="limit",
        quantity=1,
        limit_price=100.0,
    )
    with pytest.raises(DataOnlyInstrumentError):
        await submit_manual_order(
            AsyncMock(),
            body,
            user_id="u1",
            user_email="test@example.com",
        )


def test_watchlist_feed_meta_eod():
    from app.services.terminal_platform.market.watchlist_enrich import _watchlist_feed_meta

    meta = _watchlist_feed_meta("7203.T")
    assert meta["live_delayed"] == "eod"
    assert meta["data_only"] is True
    assert meta["execution_enabled"] is False
    assert meta["feed_label_ru"] == EOD_FEED_LABEL_RU


def test_lookup_marketstack_instrument():
    inst = lookup_marketstack_instrument("sap.xetra")
    assert inst is not None
    assert inst.name == "SAP SE"
    assert is_marketstack_catalog_symbol("0700.HK")
    assert canonicalize_international_symbol("005930") == "005930.KS"
    assert canonicalize_international_symbol("0700") == "0700.HK"


def test_market_data_fetch_symbols_includes_marketstack_ticker():
    from app.services.market_data.series_loader import market_data_fetch_symbols

    variants = market_data_fetch_symbols("7203.T")
    assert "7203.T" in variants


def test_router_auto_prefers_marketstack_for_catalog():
    from app.services.market_data.marketstack_catalog import is_marketstack_catalog_symbol

    assert is_marketstack_catalog_symbol("7203.T")
    assert is_marketstack_catalog_symbol("SAP.XETRA")


def test_post_order_api_rejects_data_only_symbol():
    """POST /orders for Marketstack catalog symbol → 422 with exact error body."""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints.orders import router as orders_router
    from app.core.deps import get_current_user_email, get_user_db
    from app.db.models import User, UserRole

    app = FastAPI()
    app.include_router(orders_router, prefix="/api/v1")

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
        db.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=user)
        )
        yield db

    app.dependency_overrides[get_current_user_email] = fake_user
    app.dependency_overrides[get_user_db] = fake_db

    expected_detail = (
        "7203.T: только данные — торговля недоступна "
        f"({EOD_FEED_LABEL_RU})"
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/v1/orders",
            json={
                "ticker": "7203.T",
                "side": "buy",
                "order_type": "limit",
                "quantity": 1,
                "limit_price": 2500.0,
            },
        )

    assert resp.status_code == 422
    assert resp.json() == {"detail": "По этой бумаге заявку разместить нельзя."}
    assert expected_detail  # internal reason stays in the log
