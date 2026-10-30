"""Tests for quote normalization helpers."""
from __future__ import annotations

from app.services.market_data.quote_utils import enrich_quote_fields, extract_quote_price


def test_enrich_quote_fields_fills_high_low_from_bars():
    quote = {"ticker": "MSFT", "price": 420.5, "volume": 1_000_000}
    bars = [{"high": 425.0, "low": 418.0, "volume": 2_000_000, "close": 420.5}]
    enriched = enrich_quote_fields(quote, bars)
    assert enriched["high"] == 425.0
    assert enriched["low"] == 418.0
    assert enriched["volume"] == 1_000_000


def test_enrich_quote_fields_maps_day_high_aliases():
    quote = {"ticker": "MSFT", "price": 420.5, "regularMarketDayHigh": 425.0, "regularMarketDayLow": 418.0}
    enriched = enrich_quote_fields(quote, None)
    assert enriched["high"] == 425.0
    assert enriched["low"] == 418.0


def test_extract_quote_price_from_bid_ask_mid():
    assert extract_quote_price({"bid": 100.0, "ask": 102.0}) == 101.0
