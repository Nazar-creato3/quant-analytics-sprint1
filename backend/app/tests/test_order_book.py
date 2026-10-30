"""Tests for real order book fetchers (no synthetic depth)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.orders import OrderBookLevel, OrderBookSnapshot
from app.services.orders.order_book import _fetch_binance_depth, fetch_order_book


@pytest.mark.asyncio
async def test_fetch_binance_depth_parses_levels():
    mock_resp = {
        "bids": [["0.752100", "15234.5"], ["0.752000", "8900.0"], ["0.751900", "42000.1"]],
        "asks": [["0.752200", "6012.3"], ["0.752300", "3100.0"], ["0.752400", "9900.7"]],
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return mock_resp

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    with patch("app.services.orders.order_book.httpx.AsyncClient", return_value=FakeClient()):
        book = await _fetch_binance_depth("ADAUSDT", levels=3)

    assert book.source == "binance_depth"
    assert len(book.bids) == 3
    assert len(book.asks) == 3
    assert book.bids[0].price == 0.7521
    assert book.asks[0].price == 0.7522
    assert book.bids[0].size != book.bids[1].size
    assert book.mid_price is not None
    assert book.spread_bps is not None
    assert book.spread_bps > 0


@pytest.mark.asyncio
async def test_fetch_order_book_routes_crypto_without_synthetic_sizes():
    sample = OrderBookSnapshot(
        ticker="BTCUSDT",
        bids=[OrderBookLevel(price=65000.1, size=0.52)],
        asks=[OrderBookLevel(price=65000.2, size=0.33)],
        mid_price=65000.15,
        spread_bps=0.15,
        source="binance_depth",
    )
    with patch(
        "app.services.orders.order_book._fetch_binance_depth",
        new_callable=AsyncMock,
        return_value=sample,
    ):
        book = await fetch_order_book("BTCUSDT", levels=2)

    sizes = [lvl.size for lvl in book.bids + book.asks]
    assert 1000.0 not in sizes
    assert 1300.0 not in sizes


@pytest.mark.asyncio
async def test_fetch_binance_depth_empty_on_network_error():
    class BrokenClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            raise OSError("network down")

    with patch("app.services.orders.order_book.httpx.AsyncClient", return_value=BrokenClient()):
        book = await _fetch_binance_depth("BTCUSDT", levels=5)

    assert book.bids == []
    assert book.asks == []
    assert book.mid_price is None
    assert book.source == "binance_error"


@pytest.mark.asyncio
async def test_yfinance_nbbo_uses_prices_without_fake_sizes():
    from app.services.orders.order_book import _fetch_yfinance_nbbo

    class FakeYF:
        async def get_latest_quote(self, ticker: str):
            return {"bid": 100.0, "ask": 100.5, "price": 100.25}

    with patch("app.services.market_data.client.YFinanceClient", return_value=FakeYF()):
        book = await _fetch_yfinance_nbbo("MSFT")

    assert book.source == "yfinance_nbbo_thin"
    assert len(book.bids) == 1
    assert len(book.asks) == 1
    assert book.bids[0].size == 0.0
    assert book.asks[0].size == 0.0
    assert book.depth_available is False
    assert book.session_label is not None
    assert book.depth_unavailable_reason is not None
    assert book.spread_bps is not None


@pytest.mark.asyncio
async def test_yfinance_nbbo_surfaces_prior_provider_failures():
    from app.services.orders.order_book import _fetch_yfinance_nbbo

    class FakeYF:
        async def get_latest_quote(self, ticker: str):
            return {"bid": 10.0, "ask": 10.1}

    with patch("app.services.market_data.client.YFinanceClient", return_value=FakeYF()):
        book = await _fetch_yfinance_nbbo(
            "NVDA",
            prior_reasons=["Alpaca: таймаут соединения", "Polygon: нет подписки"],
        )

    assert book.source == "yfinance_nbbo_thin"
    assert "Alpaca" in (book.depth_unavailable_reason or "")
    assert "Polygon" in (book.depth_unavailable_reason or "")
    assert "Yahoo" in (book.session_label or "") or "fallback" in (book.session_label or "")


@pytest.mark.asyncio
async def test_alpaca_nbbo_always_single_level_and_depth_unavailable():
    from app.services.orders.order_book import _try_alpaca_equity_book

    quote_payload = {
        "quote": {
            "bp": 500.68,
            "bs": 120,
            "ap": 500.72,
            "as": 85,
        }
    }

    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return quote_payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            return FakeResponse()

    with (
        patch("app.core.config.settings.ALPACA_API_KEY", "test-key"),
        patch("app.core.config.settings.ALPACA_SECRET_KEY", "test-secret"),
        patch("app.services.orders.order_book.httpx.AsyncClient", return_value=FakeClient()),
    ):
        snap, reason = await _try_alpaca_equity_book("SPY", levels=15)

    assert reason == ""
    assert snap is not None
    assert snap.source == "alpaca_nbbo_iex"
    assert len(snap.bids) == 1
    assert len(snap.asks) == 1
    assert snap.bids[0].size == 120.0
    assert snap.asks[0].size == 85.0
    assert snap.depth_available is False
    assert snap.session_label == "глубина ограничена уровнем NBBO"
    assert "1 bid + 1 ask" in (snap.depth_unavailable_reason or "")


@pytest.mark.asyncio
async def test_fetch_order_book_routes_us_to_alpaca():
    sample = OrderBookSnapshot(
        ticker="TSLA",
        bids=[OrderBookLevel(price=250.1, size=400.0), OrderBookLevel(price=250.0, size=800.0)],
        asks=[OrderBookLevel(price=250.2, size=300.0), OrderBookLevel(price=250.3, size=500.0)],
        mid_price=250.15,
        spread_bps=4.0,
        source="alpaca_nbbo",
    )
    with patch(
        "app.services.orders.order_book._fetch_alpaca_depth",
        new_callable=AsyncMock,
        return_value=sample,
    ):
        book = await fetch_order_book("TSLA", levels=5)

    assert book.source == "alpaca_nbbo"
    assert len(book.bids) >= 1
    assert len(book.asks) >= 1
    bid_vol = sum(l.size for l in book.bids)
    ask_vol = sum(l.size for l in book.asks)
    assert bid_vol != ask_vol or bid_vol > 1


@pytest.mark.asyncio
async def test_us_depth_prefers_polygon_when_alpaca_unreachable():
    from app.services.orders.order_book import _fetch_alpaca_depth

    polygon_snap = OrderBookSnapshot(
        ticker="NVDA",
        bids=[OrderBookLevel(price=100.0, size=5.0)],
        asks=[OrderBookLevel(price=100.1, size=4.0)],
        mid_price=100.05,
        spread_bps=10.0,
        source="polygon_quotes",
    )

    with (
        patch(
            "app.services.market_data.client._provider_api_keys_configured",
            return_value=True,
        ),
        patch(
            "app.services.orders.order_book._try_alpaca_equity_book",
            new_callable=AsyncMock,
            return_value=(None, "таймаут соединения"),
        ),
        patch(
            "app.services.orders.order_book._fetch_polygon_quote_depth",
            new_callable=AsyncMock,
            return_value=(polygon_snap, None),
        ),
    ):
        book = await _fetch_alpaca_depth("NVDA", levels=5)

    assert book.source == "polygon_quotes"
    assert book.depth_available is True
    assert book.bids[0].size == 5.0


@pytest.mark.asyncio
async def test_fetch_moex_depth_uses_tbank_when_iss_empty():
    from app.services.orders.order_book import _fetch_moex_depth

    tbank_book = OrderBookSnapshot(
        ticker="GAZP",
        bids=[
            OrderBookLevel(price=128.50, size=1500.0),
            OrderBookLevel(price=128.45, size=3200.0),
        ],
        asks=[
            OrderBookLevel(price=128.55, size=900.0),
            OrderBookLevel(price=128.60, size=2100.0),
        ],
        mid_price=128.525,
        spread_bps=3.89,
        source="tbank_orderbook",
        depth_available=True,
    )

    empty_iss = {"orderbook": {"columns": ["BUYSELL", "PRICE", "QUANTITY"], "data": []}}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return empty_iss

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    with (
        patch(
            "app.services.broker.tinkoff_market_data.fetch_tinkoff_order_book",
            new_callable=AsyncMock,
            return_value=tbank_book,
        ),
        patch(
            "app.services.market_data.moex_iss_client.fetch_moex_share_orderbook_json",
            new_callable=AsyncMock,
            return_value=empty_iss,
        ),
    ):
        book = await _fetch_moex_depth("GAZP", levels=10)

    assert book.source == "tbank_orderbook"
    assert book.depth_available is True
    assert len(book.bids) == 2
    assert book.bids[0].size == 1500.0
    assert book.asks[0].price == 128.55


@pytest.mark.asyncio
async def test_fetch_moex_depth_falls_back_to_iss_when_tbank_unconfigured():
    from app.services.orders.order_book import _fetch_moex_depth

    iss_rows = {
        "orderbook": {
            "columns": ["BUYSELL", "PRICE", "QUANTITY"],
            "data": [["B", 128.50, 500], ["S", 128.55, 700]],
        }
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return iss_rows

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    with (
        patch(
            "app.services.broker.tinkoff_market_data.fetch_tinkoff_order_book",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.market_data.moex_iss_client.fetch_moex_share_orderbook_json",
            new_callable=AsyncMock,
            return_value=iss_rows,
        ),
    ):
        book = await _fetch_moex_depth("SBER", levels=5)

    assert book.source == "moex_iss_orderbook"
    assert book.depth_available is True
    assert book.bids[0].size == 500.0


@pytest.mark.asyncio
async def test_tinkoff_order_book_parses_gazp_response():
    from app.services.broker.tinkoff_market_data import fetch_tinkoff_order_book

    mock_payload = {
        "figi": "BBG004730RP0",
        "depth": 10,
        "bids": [
            {"price": {"units": "128", "nano": 500000000}, "quantity": "1500"},
            {"price": {"units": "128", "nano": 450000000}, "quantity": "3200"},
        ],
        "asks": [
            {"price": {"units": "128", "nano": 550000000}, "quantity": "900"},
            {"price": {"units": "128", "nano": 600000000}, "quantity": "2100"},
        ],
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return mock_payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    with (
        patch("app.services.broker.tinkoff_market_data._tinkoff_token", return_value="test-token"),
        patch(
            "app.services.broker.tinkoff_market_data._resolve_figi",
            return_value="BBG004730RP0",
        ),
        patch("app.services.broker.tinkoff_market_data.httpx.AsyncClient", return_value=FakeClient()),
    ):
        book = await fetch_tinkoff_order_book("GAZP", levels=10)

    assert book is not None
    assert book.source == "tbank_orderbook"
    assert book.ticker == "GAZP"
    assert book.depth_available is True
    assert book.bids[0].price == 128.5
    assert book.bids[0].size == 1500.0
    assert book.asks[0].price == 128.55
    assert book.spread_bps is not None
