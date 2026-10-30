"""Tests for market data freshness (Binance live price, cache TTLs, bar patching)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.market_data.binance_spot import (
    CRYPTO_QUOTE_CACHE_TTL,
    get_crypto_quote,
    get_live_crypto_price,
    get_ws_live_price,
    live_ws_cache_key,
    normalize_crypto_ticker,
    ticker_to_binance_symbol,
)
from app.services.market_data.bars import (
    CRYPTO_BARS_MAX_CACHE_TTL,
    _BARS_CACHE_TTL,
    _BARS_CACHE_TTL_CRYPTO,
    _BARS_CACHE_TTL_INTRADAY,
    _patch_live_crypto_close,
)
from app.schemas.schemas import OHLCVBarOut


def test_ticker_to_binance_symbol_btc():
    assert ticker_to_binance_symbol("BTC-USD") == "BTCUSDT"


def test_ticker_to_binance_symbol_bare_sol():
    assert ticker_to_binance_symbol("SOL") == "SOLUSDT"
    assert normalize_crypto_ticker("SOL") == "SOL-USD"


def test_crypto_cache_ttls_are_short():
    assert CRYPTO_QUOTE_CACHE_TTL <= 5
    assert _BARS_CACHE_TTL_CRYPTO <= 5
    assert CRYPTO_BARS_MAX_CACHE_TTL <= 5


def test_equity_cache_ttls_reduced():
    assert _BARS_CACHE_TTL <= 120
    assert _BARS_CACHE_TTL_INTRADAY <= 30


def test_live_ws_cache_key():
    assert live_ws_cache_key("BTCUSDT") == "live:binance:btcusdt"


@pytest.mark.asyncio
async def test_get_ws_live_price_reads_redis():
    with patch("app.services.market_data.binance_spot.cache_get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "price": "67234.50",
            "event_time": 1_700_000_000_000,
            "source": "binance_ws",
        }
        result = await get_ws_live_price("BTCUSDT")
        assert result is not None
        assert result["price"] == 67234.50
        assert result["source"] == "binance_ws"
        mock_get.assert_called_once_with("live:binance:btcusdt")


@pytest.mark.asyncio
async def test_get_crypto_quote_prefers_ws_over_rest():
    with (
        patch("app.services.market_data.binance_spot.get_ws_live_price", new_callable=AsyncMock) as mock_ws,
        patch("app.services.market_data.binance_spot.cache_get", new_callable=AsyncMock) as mock_cache,
        patch("app.services.market_data.binance_spot._binance_get", new_callable=AsyncMock) as mock_rest,
    ):
        mock_ws.return_value = {
            "price": 67100.0,
            "timestamp": "2026-07-18T00:00:00+00:00",
            "source": "binance_ws",
        }
        mock_cache.return_value = {"change_pct": 1.5, "bid": 67099.0, "ask": 67101.0, "volume": 1000.0}

        quote = await get_crypto_quote("BTC-USD")
        assert quote is not None
        assert quote["price"] == 67100.0
        assert quote["source"] == "binance_ws"
        mock_rest.assert_not_called()


@pytest.mark.asyncio
async def test_get_live_crypto_price_force_refresh_skips_ws():
    with (
        patch("app.services.market_data.binance_spot.get_ws_live_price", new_callable=AsyncMock) as mock_ws,
        patch(
            "app.services.market_data.binance_spot.get_crypto_quote",
            new_callable=AsyncMock,
            return_value={"price": 67000.0, "source": "binance_rest"},
        ) as mock_quote,
    ):
        price = await get_live_crypto_price("BTC-USD", force_refresh=True)
        assert price == 67000.0
        mock_ws.assert_not_called()
        mock_quote.assert_called_once_with("BTC-USD", force_refresh=True)


@pytest.mark.asyncio
async def test_patch_live_crypto_close_updates_last_bar():
    bars = [
        OHLCVBarOut(
            ticker="BTC-USD",
            timeframe="1d",
            timestamp="2026-07-17T00:00:00+00:00",
            open=66000.0,
            high=66500.0,
            low=65500.0,
            close=66200.0,
            volume=100.0,
        ),
        OHLCVBarOut(
            ticker="BTC-USD",
            timeframe="1d",
            timestamp="2026-07-18T00:00:00+00:00",
            open=66200.0,
            high=66300.0,
            low=66100.0,
            close=66250.0,
            volume=50.0,
        ),
    ]
    with patch(
        "app.services.market_data.bars.get_live_crypto_price",
        new_callable=AsyncMock,
        return_value=67100.0,
    ):
        patched = await _patch_live_crypto_close("BTC-USD", bars)
        assert patched[-1].close == 67100.0
        assert patched[-1].high == 67100.0
        assert patched[-1].low == 66100.0
