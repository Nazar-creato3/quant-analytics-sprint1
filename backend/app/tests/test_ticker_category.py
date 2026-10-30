"""Tests for automatic ticker category detection."""
from __future__ import annotations

from app.domain.enums import AssetCategory, InstrumentSource
from app.services.instrument.category import (
    detect_ticker_category,
    enrich_watchlist_entry,
    watchlist_filter_key,
)


class TestTickerCategoryDetection:
    def test_aapl_us_tech_equity(self):
        info = detect_ticker_category("AAPL")
        assert info.category == AssetCategory.EQUITIES
        assert info.market == "us"
        assert info.sector == "technology"
        assert "US equity" in info.label
        assert "технологии" in info.label_ru.lower() or "technology" in info.label.lower()
        assert info.source == InstrumentSource.FINAM
        assert watchlist_filter_key(info) == "tech"

    def test_sber_moex(self):
        info = detect_ticker_category("SBER")
        assert info.category == AssetCategory.EQUITIES
        assert info.market == "moex"
        assert "MOEX" in info.label
        assert info.source == InstrumentSource.MOEX
        assert watchlist_filter_key(info) == "other"

    def test_unknown_maps_to_other(self):
        info = detect_ticker_category("ZZZZQ")
        assert info.category == AssetCategory.OTHER
        assert info.market == "other"
        assert info.label == "other"
        assert watchlist_filter_key(info) == "other"

    def test_crypto_detection(self):
        info = detect_ticker_category("BTC-USD")
        assert info.category == AssetCategory.CRYPTO
        assert info.market == "crypto"
        assert watchlist_filter_key(info) == "crypto"

    def test_eth_crypto(self):
        info = detect_ticker_category("ETH")
        assert info.category == AssetCategory.CRYPTO
        assert watchlist_filter_key(info) == "crypto"

    def test_eth_usd_crypto(self):
        info = detect_ticker_category("ETH-USD")
        assert info.category == AssetCategory.CRYPTO
        assert watchlist_filter_key(info) == "crypto"

    def test_ethereum_alias_crypto(self):
        info = detect_ticker_category("Ethereum")
        assert info.category == AssetCategory.CRYPTO
        assert watchlist_filter_key(info) == "crypto"

    def test_etf_detection(self):
        info = detect_ticker_category("GLD")
        assert info.category == AssetCategory.ETF
        assert info.market == "etf"
        assert watchlist_filter_key(info) == "etf"

    def test_ivv_etf(self):
        info = detect_ticker_category("IVV")
        assert info.category == AssetCategory.ETF
        assert info.market == "etf"
        assert watchlist_filter_key(info) == "etf"

    def test_eur_usd_fx_not_crypto(self):
        info = detect_ticker_category("EUR/USD")
        assert info.category == AssetCategory.FX
        assert info.market == "forex"
        assert watchlist_filter_key(info) == "currencies"

    def test_samsung_international_krw(self):
        info = detect_ticker_category("005930")
        assert info.category == AssetCategory.EQUITIES
        assert info.market == "asia"
        assert "KRW" in info.label

    def test_n225_international_index(self):
        info = detect_ticker_category("N225")
        assert info.category == AssetCategory.INDICES
        assert info.market == "index"


class TestEnrichWatchlistEntry:
    def test_ivv_maps_to_etf_filter(self):
        entry = enrich_watchlist_entry("IVV")
        assert entry["category"] == "etf"
        assert entry["filter_key"] == "etf"

    def test_eth_maps_to_crypto_filter(self):
        entry = enrich_watchlist_entry("ETH")
        assert entry["category"] == "crypto"
        assert entry["filter_key"] == "crypto"

    def test_unknown_maps_to_other_filter(self):
        entry = enrich_watchlist_entry("ZZZZQ")
        assert entry["category"] == "other"
        assert entry["filter_key"] == "other"
