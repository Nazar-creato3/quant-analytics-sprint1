"""Tests for World Bank macro adapter and parser."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.macro_registry.adapters.base import build_raw_response
from app.services.macro_registry.adapters.calendar import MacroCalendarAdapter
from app.services.macro_registry.adapters.world_bank import WorldBankAdapter
from app.services.macro_registry.types import MacroSourceConfig
from app.services.macro_registry.world_bank.parser import (
    load_bulk_xls_bytes,
    parse_api_payload,
    parse_bulk_csv_text,
    parse_world_bank_endpoint,
)
from app.services.macro_registry.world_bank.xls_parser import parse_bulk_xls_bytes

FIXTURES = Path(__file__).parent / "fixtures" / "macro"


def _config(source_id: str, endpoint: str, symbol: str = "WB_US_GDP_GROWTH") -> MacroSourceConfig:
    return MacroSourceConfig(
        source_id=source_id,
        category="global",
        symbol=symbol,
        endpoint=endpoint,
        refresh_interval="0 6 1 * *",
        priority=30,
        is_free=True,
        fallback_source=None,
        transformer="transform_world_bank_level",
    )


class TestWorldBankParser:
    def test_parse_endpoint_api(self):
        parsed = parse_world_bank_endpoint("adapter:world_bank:USA:NY.GDP.MKTP.KD.ZG")
        assert parsed == ("api", "USA", "NY.GDP.MKTP.KD.ZG")

    def test_parse_api_payload(self):
        payload = (FIXTURES / "world_bank_gdp_sample.json").read_text(encoding="utf-8")
        observations = parse_api_payload(
            payload,
            instrument="WB_US_GDP_GROWTH",
            country_code="USA",
            indicator_code="NY.GDP.MKTP.KD.ZG",
            unit="%",
        )
        assert len(observations) == 2
        assert observations[-1].value == pytest.approx(2.9)
        assert observations[-1].period == "2023"

    def test_parse_bulk_csv(self):
        csv_text = (FIXTURES / "world_bank_gdp_sample.csv").read_text(encoding="utf-8")
        observations = parse_bulk_csv_text(
            csv_text,
            instrument="WB_US_GDP_GROWTH",
            country_code="USA",
            indicator_code="NY.GDP.MKTP.KD.ZG",
            unit="%",
        )
        assert len(observations) == 2
        assert observations[-1].value == pytest.approx(2.5)

    def test_parse_bulk_xls(self):
        xls_path = FIXTURES / "wb_usa_gdp.xls"
        if not xls_path.exists():
            pytest.skip("wb_usa_gdp.xls fixture not present")
        observations = parse_bulk_xls_bytes(
            xls_path.read_bytes(),
            instrument="WB_US_GDP_GROWTH",
            country_code="USA",
            indicator_code="NY.GDP.MKTP.KD.ZG",
            unit="%",
        )
        assert observations
        assert observations[-1].period.isdigit()

    def test_parse_endpoint_bulk(self):
        parsed = parse_world_bank_endpoint("adapter:world_bank_bulk:USA:NY.GDP.MKTP.KD.ZG")
        assert parsed == ("bulk", "USA", "NY.GDP.MKTP.KD.ZG")


class TestWorldBankAdapter:
    def test_normalize_api_json(self):
        config = _config("wb_us_gdp_growth", "adapter:world_bank:USA:NY.GDP.MKTP.KD.ZG")
        adapter = WorldBankAdapter(config)
        payload = (FIXTURES / "world_bank_gdp_sample.json").read_text(encoding="utf-8")
        raw = build_raw_response(config, payload)
        observations = adapter.normalize(raw)
        assert observations
        assert observations[-1].instrument == "WB_US_GDP_GROWTH"


class TestInvestingCalendarAdapter:
    @pytest.mark.asyncio
    async def test_investing_calendar_maps_events(self):
        config = MacroSourceConfig(
            source_id="investing_economic_calendar",
            category="calendar",
            symbol="INVESTING_ECON_CALENDAR",
            endpoint="adapter:investing_calendar",
            refresh_interval="0 5 * * *",
            priority=5,
            is_free=False,
            fallback_source="fomc_calendar",
            transformer="transform_calendar",
        )
        adapter = MacroCalendarAdapter(config)
        sample_events = [
            {
                "event_name": "US CPI m/m",
                "event_date": "2026-08-12T12:30:00Z",
                "impact": "high",
                "estimate": "0.3",
            }
        ]

        async def _fake_fetch(*args, **kwargs):
            return sample_events

        with patch(
            "app.services.data.investing_rapidapi.is_configured",
            return_value=True,
        ), patch(
            "app.services.data.investing_rapidapi.fetch_economic_events",
            side_effect=_fake_fetch,
        ):
            entries = await adapter._build_investing_entries()

        assert len(entries) == 1
        assert entries[0].instrument == "US_CPI_YOY"
        assert entries[0].consensus_estimate == pytest.approx(0.3)
