"""Tests for MOEX / Russian equities market data."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.market_data.moex_spot import (
    get_moex_bars,
    get_moex_quote,
    is_moex_ticker,
    normalize_moex_symbol,
    normalize_watchlist_ticker,
    to_yfinance_symbol,
)
from app.services.instrument.resolver import _infer_instrument
from app.domain.enums import AssetCategory, InstrumentSource


def test_normalize_moex_symbol_strips_me_suffix():
    assert normalize_moex_symbol("SBER.ME") == "SBER"
    assert normalize_moex_symbol("sber") == "SBER"


def test_normalize_watchlist_ticker():
    assert normalize_watchlist_ticker("SBER.ME") == "SBER"
    assert normalize_watchlist_ticker("AAPL") == "AAPL"


def test_to_yfinance_symbol():
    assert to_yfinance_symbol("SBER") == "SBER.ME"
    assert to_yfinance_symbol("GAZP.ME") == "GAZP.ME"


def test_is_moex_ticker_known_and_suffix():
    assert is_moex_ticker("SBER")
    assert is_moex_ticker("SBER.ME")
    assert is_moex_ticker("GAZP")
    assert not is_moex_ticker("AAPL")


def test_infer_instrument_moex():
    source, category, _meta = _infer_instrument("SBER.ME")
    assert source == InstrumentSource.MOEX
    assert category == AssetCategory.EQUITIES


@pytest.mark.asyncio
async def test_get_moex_quote_prefers_yfinance():
    yf_quote = {
        "ticker": "SBER",
        "price": 285.5,
        "bid": 285.0,
        "ask": 286.0,
        "volume": 1_000_000,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with (
        patch(
            "app.services.market_data.moex_spot._fetch_moex_iss_quote",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.market_data.moex_spot._fetch_yfinance_quote",
            new_callable=AsyncMock,
            return_value=yf_quote,
        ) as mock_yf,
    ):
        quote = await get_moex_quote("SBER", force_refresh=True)
        assert quote is not None
        assert quote["price"] == 285.5
        assert quote["ticker"] == "SBER"
        mock_yf.assert_called_once_with("SBER")


@pytest.mark.asyncio
async def test_get_moex_quote_falls_back_to_iss():
    iss_quote = {
        "ticker": "SBER",
        "price": 284.0,
        "bid": 283.5,
        "ask": 284.5,
        "volume": 500_000,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "moex_iss",
    }
    with (
        patch(
            "app.services.market_data.moex_spot._fetch_yfinance_quote",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.market_data.moex_spot._fetch_moex_iss_quote",
            new_callable=AsyncMock,
            return_value=iss_quote,
        ) as mock_iss,
    ):
        quote = await get_moex_quote("SBER", force_refresh=True)
        assert quote is not None
        assert quote["price"] == 284.0
        assert quote["source"] == "moex_iss"
        mock_iss.assert_called_once_with("SBER")


@pytest.mark.asyncio
async def test_fetch_moex_iss_quote_prefers_tqbr_board():
    payload = {
        "securities": {
            "columns": ["SECID", "BOARDID", "PREVPRICE"],
            "data": [["SBER", "TQBR", 277.23]],
        },
        "marketdata": {
            "columns": ["SECID", "BOARDID", "LAST", "LCURRENTPRICE", "BID", "OFFER", "VOLTODAY", "LASTTOPREVPRICE"],
            "data": [
                ["SBER", "SPEQ", None, None, None, None, 0, None],
                ["SBER", "TQBR", 249.34, 249.34, 249.0, 249.5, 1000, -10.92],
            ],
        },
    }

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None):
            return _Resp()

    with patch("app.services.market_data.moex_spot.httpx.AsyncClient", return_value=_Client()):
        from app.services.market_data.moex_spot import _fetch_moex_iss_quote

        quote = await _fetch_moex_iss_quote("SBER")
        assert quote is not None
        assert quote["price"] == 249.34
        assert quote["board"] == "TQBR"


@pytest.mark.asyncio
async def test_get_moex_bars_prefers_yfinance():
    bars = [
        {
            "timestamp": "2026-07-17T00:00:00+00:00",
            "open": 280.0,
            "high": 290.0,
            "low": 278.0,
            "close": 285.0,
            "volume": 10_000_000,
        }
    ]
    with (
        patch(
            "app.services.market_data.moex_spot._fetch_moex_iss_bars",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.market_data.moex_spot._fetch_yfinance_bars",
            new_callable=AsyncMock,
            return_value=bars,
        ) as mock_yf,
    ):
        result = await get_moex_bars("GAZP", "1d", 100)
        assert len(result) == 1
        assert result[0]["close"] == 285.0
        mock_yf.assert_called_once_with("GAZP", "1d", 100)


@pytest.mark.asyncio
async def test_get_moex_bars_falls_back_to_iss():
    bars = [
        {
            "timestamp": "2026-07-17T00:00:00+00:00",
            "open": 150.0,
            "high": 155.0,
            "low": 148.0,
            "close": 152.0,
            "volume": 5_000_000,
        }
    ]
    with (
        patch(
            "app.services.market_data.moex_spot._fetch_yfinance_bars",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.market_data.moex_spot._fetch_moex_iss_bars",
            new_callable=AsyncMock,
            return_value=bars,
        ) as mock_iss,
    ):
        result = await get_moex_bars("LKOH", "1d", 50)
        assert len(result) == 1
        assert result[0]["close"] == 152.0
        mock_iss.assert_called_once_with("LKOH", "1d", 50)


@pytest.mark.asyncio
async def test_get_latest_quote_resolved_routes_moex():
    from app.services.market_data.client import get_latest_quote_resolved

    moex_quote = {"ticker": "SBER", "price": 285.0, "source": "yfinance"}
    with patch(
        "app.services.market_data.moex_spot.get_moex_quote",
        new_callable=AsyncMock,
        return_value=moex_quote,
    ) as mock_moex:
        quote = await get_latest_quote_resolved("SBER")
        assert quote["price"] == 285.0
        mock_moex.assert_called_once()
