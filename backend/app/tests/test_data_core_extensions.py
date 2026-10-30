"""Tests for Prompt 16 data core extensions (order book, macro indicators, sector seed)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.macro.indicators import (
    compute_spread_bps,
    normalize_depth_levels,
    parse_cbr_key_rate_xml,
    parse_fred_observations,
)
from app.services.macro.sector_seed import SECTOR_SEED, sector_for_symbol


class TestOrderBookHelpers:
    def test_normalize_depth_levels(self):
        raw = [["100.0", "1.5"], ["99.5", "2"]]
        assert normalize_depth_levels(raw) == [
            {"price": "100.0", "qty": "1.5"},
            {"price": "99.5", "qty": "2"},
        ]

    def test_compute_spread_bps(self):
        bids = [{"price": "100.0", "qty": "1"}]
        asks = [{"price": "100.2", "qty": "1"}]
        spread = compute_spread_bps(bids, asks)
        assert spread is not None
        assert spread == pytest.approx(19.9601, rel=1e-3)

    def test_compute_spread_bps_empty_book(self):
        assert compute_spread_bps([], [{"price": "1", "qty": "1"}]) is None


class TestCbrParser:
    def test_parse_key_rate_xml_regex(self):
        xml = """
        <KeyRateXMLResult>
          <KR><DT>2025-06-01T00:00:00</DT><Rate>21.00</Rate></KR>
          <KR><DT>2025-07-01T00:00:00</DT><Rate>20.00</Rate></KR>
        </KeyRateXMLResult>
        """
        rows = parse_cbr_key_rate_xml(xml)
        assert len(rows) == 2
        assert rows[0]["indicator_code"] == "rate_cb"
        assert rows[0]["source"] == "cbr_rf"
        assert rows[1]["value"] == Decimal("20.00")


class TestFredParser:
    def test_parse_fred_observations_skips_missing(self):
        payload = {
            "observations": [
                {"date": "2025-01-01", "value": "20.5"},
                {"date": "2025-01-02", "value": "."},
            ]
        }
        rows = parse_fred_observations("vix", payload)
        assert len(rows) == 1
        assert rows[0]["indicator_code"] == "vix"
        assert rows[0]["value"] == Decimal("20.5")


class TestSectorSeed:
    def test_known_symbols_present(self):
        assert "AAPL" in SECTOR_SEED
        assert "SBER" in SECTOR_SEED
        assert "BTCUSDT" in SECTOR_SEED

    def test_sector_for_symbol(self):
        assert sector_for_symbol("aapl") == ("technology", "consumer_electronics")
        assert sector_for_symbol("UNKNOWN") is None
