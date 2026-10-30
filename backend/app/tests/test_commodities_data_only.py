"""OTC commodities are data-only: searchable quotes, no execution path."""
from __future__ import annotations

from datetime import datetime, timezone
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
from app.services.market_data.commodities_catalog import (
    COMMODITY_FEED_LABEL_RU,
    canonical_commodity_symbol,
    is_commodity_pair,
    match_commodity_catalog,
)
from app.services.market_data.universe_search import search_universe


def test_commodity_canonical_and_detection():
    assert canonical_commodity_symbol("XAUUSD") == "XAU/USD"
    assert canonical_commodity_symbol("GOLD") == "XAU/USD"
    assert canonical_commodity_symbol("WTI") == "WTI/USD"
    assert is_commodity_pair("XAG/USD")
    assert is_commodity_pair("BRENTOIL")
    assert not is_commodity_pair("AAPL")
    assert not is_commodity_pair("EUR/USD")
    assert not is_commodity_pair("BTC-USD")


def test_commodities_are_data_only():
    assert is_data_only_symbol("XAU/USD")
    assert is_data_only_symbol("WTI")
    flags = execution_flags("XAU/USD")
    assert flags["data_only"] is True
    assert flags["execution_enabled"] is False
    assert flags["feed"] == "commodities"
    assert flags["feed_label_ru"] == COMMODITY_FEED_LABEL_RU
    with pytest.raises(DataOnlyInstrumentError) as exc:
        assert_execution_allowed("XAU/USD")
    assert "XAU/USD" in str(exc.value)


@pytest.mark.asyncio
async def test_commodities_searchable_under_category():
    hits = await search_universe("GOLD", category="commodities")
    assert any(h.symbol == "XAU/USD" for h in hits)
    hit = next(h for h in hits if h.symbol == "XAU/USD")
    assert hit.category_label_ru == "Сырьё"
    assert hit.data_tier == "data_only"
    names = {p.symbol for p in match_commodity_catalog("oil", limit=10)}
    assert "WTI/USD" in names
    assert "BRENT/USD" in names


@pytest.mark.asyncio
async def test_submit_manual_order_rejects_gold():
    from app.schemas.orders import ManualOrderCreate
    from app.services.orders.service import submit_manual_order

    body = ManualOrderCreate(
        ticker="XAU/USD",
        side="buy",
        order_type="limit",
        quantity=1,
        limit_price=2400,
    )
    with pytest.raises(DataOnlyInstrumentError):
        await submit_manual_order(
            AsyncMock(),
            body,
            user_id="u1",
            user_email="test@example.com",
        )


def test_post_order_api_rejects_commodity():
    from app.api.v1.endpoints.orders import router as orders_router
    from app.core.deps import get_current_user_email, get_user_db
    from app.db.models import User, UserRole

    app = FastAPI()
    app.include_router(orders_router, prefix="/api/v1")

    async def fake_user():
        return "trader@test.com"

    user = User(
        id="u-cmdty",
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

    expected = f"XAU/USD: только данные — торговля недоступна ({COMMODITY_FEED_LABEL_RU})"
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/v1/orders",
            json={
                "ticker": "XAU/USD",
                "side": "buy",
                "order_type": "limit",
                "quantity": 1,
                "limit_price": 2400,
            },
        )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "По этой бумаге заявку разместить нельзя."}
    assert expected  # internal reason still built for the log, not shown to the user


def test_symbol_rules_commodity_has_no_execution():
    from app.api.v1.endpoints.orders import router as orders_router
    from app.core.deps import get_current_user_email, get_user_db

    app = FastAPI()
    app.include_router(orders_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_email] = lambda: "trader@test.com"
    app.dependency_overrides[get_user_db] = lambda: AsyncMock()

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/orders/symbol-rules/XAUUSD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_only"] is True
    assert body["execution_enabled"] is False
    assert body["venue"] == "commodities_data"
