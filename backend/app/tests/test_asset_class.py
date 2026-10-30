"""Four routing classes × chart / watchlist / search — one classifier."""
from __future__ import annotations

import pytest

from app.domain.enums import AssetCategory
from app.services.instrument.asset_class import (
    RoutingClass,
    chart_api_symbol,
    classify_symbol,
    display_currency,
)
from app.services.instrument.category import detect_ticker_category, watchlist_filter_key
from app.services.market_data.binance_spot import is_crypto_ticker, normalize_crypto_ticker
from app.services.market_data.marketstack_catalog import canonicalize_international_symbol
from app.services.market_data.universe_search import search_universe


# (raw, class, chart_symbol, currency, watchlist_tab, search_category)
_MATRIX = (
    ("BTC/USDT", RoutingClass.CRYPTO_PAIR, "BTC-USD", "USD", "crypto", "crypto"),
    ("AAPL", RoutingClass.US_EQUITY_INDEX, "AAPL", "USD", "tech", "equities"),
    ("IMOEX", RoutingClass.US_EQUITY_INDEX, "IMOEX", "RUB", "other", None),
    ("EUR/USD", RoutingClass.FOREX_PAIR, "EUR/USD", "USD", "currencies", "fx"),
    ("USD/JPY", RoutingClass.FOREX_PAIR, "USD/JPY", "JPY", "currencies", "fx"),
    ("N225", RoutingClass.INTERNATIONAL, "^N225", "JPY", "other", "indices"),
    ("005930", RoutingClass.INTERNATIONAL, "005930.KS", "KRW", "other", "equities"),
)


@pytest.mark.parametrize(
    ("raw", "cls", "chart", "ccy", "tab", "_search_cat"),
    _MATRIX,
)
def test_classify_chart_watchlist_matrix(raw, cls, chart, ccy, tab, _search_cat):
    info = classify_symbol(raw)
    assert info.routing_class == cls
    assert chart_api_symbol(raw) == chart
    assert info.currency == ccy
    assert display_currency(raw) == ccy
    detected = detect_ticker_category(raw)
    assert watchlist_filter_key(detected) == tab


def test_eur_usd_is_not_crypto():
    assert normalize_crypto_ticker("EUR/USD") is None
    assert not is_crypto_ticker("EUR/USD")
    assert not is_crypto_ticker("USDJPY")
    assert classify_symbol("EUR/USD").routing_class == RoutingClass.FOREX_PAIR
    assert classify_symbol("EUR/USD").category == AssetCategory.FX


def test_samsung_canonical_and_krw_not_usd():
    assert canonicalize_international_symbol("005930") == "005930.KS"
    info = classify_symbol("005930")
    assert info.canonical_symbol == "005930.KS"
    assert info.currency == "KRW"
    assert display_currency("005930") != "USD"
    assert display_currency("AAPL") == "USD"


def test_n225_is_international_jpy():
    info = classify_symbol("N225")
    assert info.routing_class == RoutingClass.INTERNATIONAL
    assert info.chart_api_symbol == "^N225"
    assert info.currency == "JPY"
    assert info.show_volume is False


def test_usd_rub_stays_on_moex_not_otc_forex():
    info = classify_symbol("USD/RUB")
    assert info.routing_class == RoutingClass.US_EQUITY_INDEX
    assert info.market == "moex_fx"
    assert info.currency == "RUB"


def test_usd_cny_is_classic_forex():
    info = classify_symbol("USD/CNY")
    assert info.routing_class == RoutingClass.FOREX_PAIR
    assert info.currency == "CNY"


@pytest.mark.asyncio
async def test_search_covers_four_classes():
    btc = await search_universe("BTC", category="all")
    assert any(h.category == "crypto" for h in btc)

    aapl = await search_universe("AAPL", category="all")
    assert any(h.symbol == "AAPL" for h in aapl)

    fx = await search_universe("EUR/USD", category="fx")
    assert any(h.symbol == "EUR/USD" and h.category == "fx" for h in fx)

    jpy = await search_universe("USD/JPY", category="all")
    assert any(h.symbol == "USD/JPY" for h in jpy)

    n225 = await search_universe("N225", category="all")
    assert any(h.symbol == "N225" for h in n225)

    samsung = await search_universe("005930", category="all")
    assert any(h.symbol == "005930.KS" for h in samsung)

    by_name = await search_universe("Samsung", category="all")
    assert any("005930" in h.symbol for h in by_name)
