"""Tests for Eurostat bulk parser, adapter, and analysis snippets."""
from __future__ import annotations

from pathlib import Path

import pytest
import httpx

from app.services.analysis.context import format_eu_macro_snippet
from app.services.macro_registry.adapters.base import build_raw_response
from app.services.macro_registry.adapters.eurostat_bulk import EurostatBulkAdapter
from app.services.macro_registry.eurostat.indicators import spec_by_id
from app.services.macro_registry.eurostat.parser import (
    open_spec_csv_text,
    parse_eurostat_endpoint,
    parse_sdmx_csv_stream,
    parse_sdmx_csv_text,
    should_stream_spec_csv,
)
from app.services.macro_registry.types import MacroSourceConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "macro"


class TestEurostatParser:
    def test_parse_endpoint(self):
        assert parse_eurostat_endpoint("adapter:eurostat_bulk:eu_gdp_growth") == "eu_gdp_growth"
        assert parse_eurostat_endpoint("adapter:world_bank:USA:X") is None

    def test_tec00115_latest_annual_growth(self):
        spec = spec_by_id("eu_gdp_growth")
        assert spec is not None
        text = (FIXTURES / "eurostat_tec00115_sample.csv").read_text(encoding="utf-8")
        obs = parse_sdmx_csv_text(text, spec=spec)
        assert len(obs) == 3
        assert obs[-1].value == pytest.approx(1.2)
        assert obs[-1].period == "2025"

    def test_namq_yoy_quarterly_derivation(self):
        spec = spec_by_id("eu_gdp_yoy_q")
        assert spec is not None
        text = (FIXTURES / "eurostat_namq_10_gdp_sample.csv").read_text(encoding="utf-8")
        obs = parse_sdmx_csv_text(text, spec=spec)
        assert len(obs) == 1
        assert obs[0].period == "2026-Q1"
        assert obs[0].value == pytest.approx(1.980198, rel=1e-3)

    def test_namq_stream_parse_from_fixture_file(self, tmp_path):
        spec = spec_by_id("eu_gdp_yoy_q")
        assert spec is not None
        store_dir = tmp_path / "eurostat"
        store_dir.mkdir()
        dataset = store_dir / spec.dataset_file
        sample = FIXTURES / "eurostat_namq_10_gdp_sample.csv"
        dataset.write_bytes(sample.read_bytes())
        assert should_stream_spec_csv(store_dir=store_dir, roots=[], spec=spec)
        with open_spec_csv_text(store_dir=store_dir, roots=[], spec=spec) as stream:
            obs = parse_sdmx_csv_stream(stream, spec=spec)
        assert len(obs) == 1
        assert obs[0].period == "2026-Q1"
        assert obs[0].value == pytest.approx(1.980198, rel=1e-3)

    def test_eurostat_bulk_adapter_stream_marker(self, tmp_path, monkeypatch):
        spec = spec_by_id("eu_gdp_yoy_q")
        assert spec is not None
        store_dir = tmp_path / "eurostat"
        store_dir.mkdir()
        (store_dir / spec.dataset_file).write_bytes(
            (FIXTURES / "eurostat_namq_10_gdp_sample.csv").read_bytes()
        )
        monkeypatch.setattr(
            "app.services.macro_registry.adapters.eurostat_bulk.settings.EUROSTAT_STORE_DIR",
            str(store_dir),
        )
        monkeypatch.setattr(
            "app.services.macro_registry.adapters.eurostat_bulk.settings.EUROSTAT_DATA_DIR",
            "",
        )
        config = MacroSourceConfig(
            source_id="eu_gdp_yoy_q",
            category="regional",
            symbol="EU_GDP_YOY_Q",
            endpoint="adapter:eurostat_bulk:eu_gdp_yoy_q",
            refresh_interval="0 7 1 * *",
            priority=25,
            is_free=True,
            fallback_source=None,
            transformer="transform_eurostat_level",
        )
        adapter = EurostatBulkAdapter(config)
        import asyncio

        raw = asyncio.run(adapter.fetch(httpx.AsyncClient()))
        assert raw.payload.startswith("eurostat-stream:v1:")
        normalized = adapter.normalize(raw)
        assert len(normalized) == 1
        assert normalized[0].value == pytest.approx(1.980198, rel=1e-3)


class TestEurostatAdapter:
    def test_normalize_from_fixture_csv(self):
        spec = spec_by_id("eu_gdp_growth")
        assert spec is not None
        config = MacroSourceConfig(
            source_id="eu_gdp_growth",
            category="regional",
            symbol="EU_GDP_GROWTH",
            endpoint="adapter:eurostat_bulk:eu_gdp_growth",
            refresh_interval="0 7 1 * *",
            priority=25,
            is_free=True,
            fallback_source=None,
            transformer="transform_eurostat_level",
        )
        adapter = EurostatBulkAdapter(config)
        payload = (FIXTURES / "eurostat_tec00115_sample.csv").read_text(encoding="utf-8")
        raw = build_raw_response(config, payload, content_type="text/csv")
        normalized = adapter.normalize(raw)
        assert normalized[-1].value == pytest.approx(1.2)


class TestEuMacroSnippet:
    def test_format_eu_macro_snippet(self):
        text = format_eu_macro_snippet(
            {
                "eu_gdp_growth": 1.2,
                "eu_gdp_yoy_q": 0.48,
            }
        )
        assert "Eurostat" in text
        assert "1.2%" in text
        assert "0.5%" in text or "0.48%" in text
