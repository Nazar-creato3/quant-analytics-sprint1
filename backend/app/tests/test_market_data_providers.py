"""Tests for MOEX ISS and FMP fundamentals providers."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.market_data.enrichment import fetch_fundamentals
from app.services.market_data.fmp_provider import fetch_fmp_fundamentals
from app.services.market_data.moex_iss_provider import (
    _fetch_index_quote_sync,
    fetch_moex_fundamentals,
    fetch_moex_history,
    fetch_moex_index_quote,
    list_moex_securities,
)


@pytest.mark.asyncio
async def test_fetch_moex_index_quote_imoex_live_or_mocked():
    """IMOEX index quote uses ISS index market (CURRENTVALUE when LAST absent)."""
    mocked_rows = [{"SECID": "IMOEX", "CURRENTVALUE": 2281.31, "TIME": "19:00:00"}]
    with patch(
        "app.services.market_data.moex_iss_provider._fetch_index_marketdata_sync",
        return_value=mocked_rows,
    ), patch(
        "app.services.market_data.moex_iss_provider._index_change_pct_from_history_sync",
        return_value=-0.42,
    ):
        result = _fetch_index_quote_sync("IMOEX")
    assert result is not None
    assert result["symbol"] == "IMOEX"
    assert result["price"] == 2281.31
    assert result["change_pct"] == -0.42
    assert result["source"] == "moex_iss_index"


@pytest.mark.asyncio
async def test_fetch_moex_index_quote_rejects_duplicate_iss_meta():
    """ISSClient args must not duplicate apimoex BASE_QUERY keys (Py 3.14+)."""
    from app.services.market_data.moex_iss_provider import _iss_client_args

    args = _iss_client_args({"iss.meta": "off", "iss.only": "marketdata"})
    assert "iss.meta" not in args
    assert args["iss.only"] == "marketdata"


@pytest.mark.asyncio
async def test_fetch_moex_index_quote_async_wrapper():
    payload = {
        "symbol": "RTSI",
        "price": 874.64,
        "change_pct": 0.15,
        "source": "moex_iss_index",
    }
    with patch(
        "app.services.market_data.moex_iss_provider._fetch_index_quote_sync",
        return_value=payload,
    ):
        result = await fetch_moex_index_quote("RTSI")
    assert result == payload


@pytest.mark.asyncio
async def test_fetch_moex_fundamentals_from_iss_detail():
    detail = {
        "symbol": "SBER",
        "short_name": "Sberbank",
        "price": 285.5,
        "market_cap": 6_400_000_000_000.0,
        "issuesize": 21_586_948_000,
        "currency": "RUB",
    }
    with patch(
        "app.services.market_data.moex_iss_provider._fetch_security_detail_sync",
        return_value=detail,
    ):
        result = await fetch_moex_fundamentals("SBER")
    assert result["symbol"] == "SBER"
    assert result["exchange"] == "MOEX"
    assert result["market_cap"] == 6_400_000_000_000.0
    assert result["source"] == "moex_iss"


@pytest.mark.asyncio
async def test_fetch_moex_history_via_apimoex():
    rows = [
        {
            "TRADEDATE": "2026-07-21",
            "OPEN": 280.0,
            "HIGH": 290.0,
            "LOW": 278.0,
            "CLOSE": 285.0,
            "VOLUME": 10_000_000,
            "WAPRICE": 284.5,
            "NUMTRADES": 12000,
        }
    ]
    with patch(
        "app.services.market_data.moex_iss_provider.apimoex.get_board_history",
        return_value=rows,
    ):
        bars = await fetch_moex_history("GAZP", limit=10)
    assert len(bars) == 1
    assert bars[0]["close"] == 285.0
    assert bars[0]["volume"] == 10_000_000


@pytest.mark.asyncio
async def test_list_moex_securities():
    securities = [{"SECID": "SBER", "SHORTNAME": "Sberbank"}]
    mock_iss = MagicMock()
    mock_iss.get.return_value = {"securities": securities}
    with (
        patch("app.services.market_data.moex_iss_provider.apimoex.ISSClient", return_value=mock_iss),
        patch("app.services.market_data.moex_iss_provider._build_session") as mock_session,
    ):
        mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        result = await list_moex_securities()
    assert result[0]["SECID"] == "SBER"


@pytest.mark.asyncio
async def test_fetch_fmp_fundamentals_normalizes_profile():
    profile = [
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "mktCap": 3_000_000_000_000,
            "pe": 28.5,
            "eps": 6.5,
            "beta": 1.2,
            "exchangeShortName": "NASDAQ",
            "currency": "USD",
            "sector": "Technology",
            "range": "164.08-260.10",
        }
    ]
    metrics = [{"peRatio": 28.5, "roe": 1.47, "marketCap": 3_000_000_000_000}]
    income = [{"revenue": 400_000_000_000, "netIncome": 100_000_000_000, "eps": 6.5}]

    async def _fake_get(client, path, **params):
        if path.startswith("/profile/"):
            return profile
        if path.startswith("/key-metrics/"):
            return metrics
        if path.startswith("/income-statement/"):
            return income
        return None

    with (
        patch("app.services.market_data.fmp_provider.get_settings") as mock_settings,
        patch("app.services.market_data.fmp_provider._fmp_get", side_effect=_fake_get),
    ):
        mock_settings.return_value.FMP_API_KEY = "test-key"
        result = await fetch_fmp_fundamentals("AAPL")

    assert result["symbol"] == "AAPL"
    assert result["market_cap"] == 3_000_000_000_000
    assert result["pe_ratio"] == 28.5
    assert result["revenue"] == 400_000_000_000
    assert result["source"] == "fmp"
    assert result["week52_low"] == 164.08
    assert result["week52_high"] == 260.10


@pytest.mark.asyncio
async def test_fetch_fmp_skips_crypto():
    with patch("app.services.market_data.fmp_provider.get_settings") as mock_settings:
        mock_settings.return_value.FMP_API_KEY = "test-key"
        result = await fetch_fmp_fundamentals("BTC-USD")
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_fundamentals_moex_prefers_iss():
    moex = {"symbol": "SBER", "exchange": "MOEX", "market_cap": 6e12, "source": "moex_iss"}
    with (
        patch(
            "app.services.market_data.moex_iss_provider.fetch_moex_fundamentals",
            new_callable=AsyncMock,
            return_value=moex,
        ),
        patch(
            "app.services.market_data.enrichment._fetch_yfinance_fundamentals",
            new_callable=AsyncMock,
        ) as mock_yf,
    ):
        result = await fetch_fundamentals("SBER")
    assert result["market_cap"] == 6e12
    assert result["source"] == "moex_iss"
    mock_yf.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_fundamentals_us_prefers_fmp():
    fmp = {"symbol": "AAPL", "market_cap": 3e12, "pe_ratio": 28.5, "source": "fmp"}
    with (
        patch(
            "app.services.market_data.fmp_provider.fetch_fmp_fundamentals",
            new_callable=AsyncMock,
            return_value=fmp,
        ),
        patch(
            "app.services.market_data.enrichment._fetch_yfinance_fundamentals",
            new_callable=AsyncMock,
        ) as mock_yf,
    ):
        result = await fetch_fundamentals("AAPL")
    assert result["pe_ratio"] == 28.5
    assert result["source"] == "fmp"
    mock_yf.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_fundamentals_moex_falls_back_to_yfinance():
    moex = {"symbol": "SBER", "exchange": "MOEX", "price": 285.0, "source": "moex_iss"}
    yf = {"market_cap": 6e12, "pe_ratio": 5.2, "source": "yfinance"}
    with (
        patch(
            "app.services.market_data.moex_iss_provider.fetch_moex_fundamentals",
            new_callable=AsyncMock,
            return_value=moex,
        ),
        patch(
            "app.services.market_data.enrichment._fetch_yfinance_fundamentals",
            new_callable=AsyncMock,
            return_value=yf,
        ),
    ):
        result = await fetch_fundamentals("SBER")
    assert result["market_cap"] == 6e12
    assert result["price"] == 285.0
    assert result["source"] == "moex_iss"


@pytest.mark.asyncio
async def test_get_bars_resolved_falls_back_to_yfinance_on_alpaca_error():
    from datetime import datetime, timezone

    from app.services.market_data.client import get_bars_resolved, reset_market_data_client

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    yf_bars = [
        {
            "timestamp": "2025-06-01T00:00:00",
            "close": 100.0,
            "open": 99.0,
            "high": 101.0,
            "low": 98.0,
            "volume": 1e6,
        }
    ]

    yf_inst = MagicMock()
    yf_inst.get_bars = AsyncMock(return_value=yf_bars)
    alpaca = AsyncMock()
    alpaca.get_bars = AsyncMock(side_effect=RuntimeError("401 Unauthorized"))

    with patch(
        "app.services.market_data.client.build_equity_client_chain",
        return_value=[("alpaca", alpaca), ("yfinance", yf_inst)],
    ):
        reset_market_data_client()
        bars = await get_bars_resolved("AAPL", "1d", start, end)

    assert bars[0]["close"] == 100.0
    alpaca.get_bars.assert_awaited_once()
    yf_inst.get_bars.assert_awaited_once()


@pytest.mark.asyncio
async def test_equity_chain_prefers_first_keyed_provider():
    from datetime import datetime, timezone

    from app.services.market_data.client import get_latest_quote_resolved, reset_market_data_client

    primary = AsyncMock()
    primary.get_latest_quote = AsyncMock(
        return_value={"ticker": "AAPL", "price": 190.0, "source": "alpaca"}
    )
    secondary = AsyncMock()
    secondary.get_latest_quote = AsyncMock(
        return_value={"ticker": "AAPL", "price": 191.0, "source": "yfinance"}
    )

    with (
        patch(
            "app.services.market_data.client.build_equity_client_chain",
            return_value=[("alpaca", primary), ("yfinance", secondary)],
        ),
        patch("app.utils.cache.cache_get", new_callable=AsyncMock, return_value=None),
        patch("app.utils.cache.cache_set", new_callable=AsyncMock),
        patch("app.utils.cache.cache_delete", new_callable=AsyncMock),
    ):
        reset_market_data_client()
        quote = await get_latest_quote_resolved("AAPL", force_refresh=True)

    assert quote["price"] == 190.0
    assert quote["source"] == "alpaca"
    primary.get_latest_quote.assert_awaited_once()
    secondary.get_latest_quote.assert_not_awaited()


def test_configured_provider_flags_names_only():
    from app.services.market_data.http_providers import configured_provider_flags

    flags = configured_provider_flags()
    assert set(flags) >= {
        "alpaca",
        "polygon",
        "twelvedata",
        "tiingo",
        "marketstack",
        "finnhub",
        "coingecko",
        "yfinance",
    }
    assert all(isinstance(v, bool) for v in flags.values())


def test_moex_session_disables_env_proxy():
    from app.services.market_data.moex_iss_provider import _build_session

    session = _build_session()
    assert session.trust_env is False
    session.close()

