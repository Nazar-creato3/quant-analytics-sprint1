from unittest.mock import patch

import pytest

from app.services.market_data.koyfin_snapshot import fetch_fmp_fundamentals_snapshot, fetch_fmp_screener


@pytest.mark.asyncio
async def test_fetch_fmp_screener_normalizes_rows():
    rows = [
        {
            "symbol": "NVDA",
            "companyName": "NVIDIA",
            "exchangeShortName": "NASDAQ",
            "sector": "Technology",
            "price": 120.5,
            "marketCap": 3e12,
            "beta": 1.7,
            "volume": 4e7,
            "pe": 42.1,
            "lastAnnualDividend": 0.04,
            "country": "US",
        }
    ]

    async def _fake_get(client, path, **params):
        assert path == "/stock-screener"
        return rows

    with (
        patch("app.services.market_data.koyfin_snapshot.get_settings") as mock_settings,
        patch("app.services.market_data.koyfin_snapshot._fmp_get", side_effect=_fake_get),
    ):
        mock_settings.return_value.FMP_API_KEY = "test-key"
        out = await fetch_fmp_screener({"sector": "Technology"}, limit=10)

    assert out[0]["symbol"] == "NVDA"
    assert out[0]["source"] == "fmp"
    assert out[0]["price"] == 120.5
    assert out[0]["pe"] == 42.1
    assert abs(out[0]["dividend"] - 0.04 / 120.5) < 1e-12  # yield, not the dollar amount


@pytest.mark.asyncio
async def test_fundamentals_snapshot_merges_ratios():
    async def _fake_get(client, path, **params):
        if path.startswith("/ratios/"):
            return [{"grossProfitMargin": 0.42, "priceToSalesRatio": 8.1}]
        if path.startswith("/key-metrics-ttm"):
            return [{"pegRatioTTM": 1.4, "roicTTM": 0.28}]
        if path.startswith("/ratios-ttm"):
            return [{"operatingProfitMarginTTM": 0.31}]
        return None

    with (
        patch("app.services.market_data.koyfin_snapshot.get_settings") as mock_settings,
        patch(
            "app.services.market_data.koyfin_snapshot.fetch_fmp_fundamentals",
            return_value={"symbol": "AAPL", "pe_ratio": 28.5, "source": "fmp"},
        ),
        patch("app.services.market_data.koyfin_snapshot._fmp_get", side_effect=_fake_get),
    ):
        mock_settings.return_value.FMP_API_KEY = "test-key"
        out = await fetch_fmp_fundamentals_snapshot("AAPL")

    assert out["pe_ratio"] == 28.5
    assert out["gross_margin"] == 0.42
    assert out["peg"] == 1.4
    assert out["roic"] == 0.28
    assert out["ratios_source"] == "fmp_ratios"
