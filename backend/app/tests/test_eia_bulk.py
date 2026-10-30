"""Tests for EIA bulk macro adapter and parser."""
from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.macro_registry.adapters.base import build_raw_response
from app.services.macro_registry.adapters.eia_bulk import EiaBulkAdapter
from app.services.macro_registry.eia.parser import (
    load_bulk_series,
    parse_eia_endpoint,
    parse_eia_series_payload,
)
from app.services.macro_registry.types import MacroSourceConfig

FIXTURES = Path(__file__).parent / "fixtures" / "macro"


def _config(source_id: str, endpoint: str, symbol: str = "BRENT_OIL") -> MacroSourceConfig:
    return MacroSourceConfig(
        source_id=source_id,
        category="energy",
        symbol=symbol,
        endpoint=endpoint,
        refresh_interval="0 14 * * 1-5",
        priority=15,
        is_free=True,
        fallback_source=None,
        transformer="transform_eia_level",
    )


class TestEiaParser:
    def test_parse_endpoint(self):
        assert parse_eia_endpoint("adapter:eia:PET.RBRTE.D") == ("auto", "PET.RBRTE.D")
        assert parse_eia_endpoint("adapter:eia_bulk:PET.RWTC.D") == ("bulk", "PET.RWTC.D")

    def test_parse_series_payload(self):
        payload = (FIXTURES / "eia_brent_sample.json").read_text(encoding="utf-8")
        observations = parse_eia_series_payload(
            payload,
            instrument="BRENT_OIL",
            series_id="PET.RBRTE.D",
            unit="USD/barrel",
            currency="USD",
        )
        assert len(observations) == 3
        assert observations[-1].value == pytest.approx(77.8)
        assert observations[-1].period == "2024-01-04"

    def test_load_bulk_series_from_mock_zip(self):
        sample = (FIXTURES / "eia_brent_sample.json").read_text(encoding="utf-8")
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("PET.txt", sample + "\n")
        buffer.seek(0)
        zip_path = Path(__file__).parent / "PET.zip"
        zip_path.write_bytes(buffer.getvalue())
        try:
            payload = load_bulk_series(zip_path.parent, series_id="PET.RBRTE.D")
            assert payload is not None
            assert json.loads(payload)["series_id"] == "PET.RBRTE.D"
        finally:
            zip_path.unlink(missing_ok=True)


class TestEiaBulkAdapter:
    def test_normalize_bulk_json(self):
        config = _config("eia_brent_spot", "adapter:eia:PET.RBRTE.D")
        adapter = EiaBulkAdapter(config)
        payload = (FIXTURES / "eia_brent_sample.json").read_text(encoding="utf-8")
        raw = build_raw_response(config, payload)
        observations = adapter.normalize(raw)
        assert observations
        assert observations[-1].instrument == "BRENT_OIL"
        assert observations[-1].unit == "USD/barrel"

    @pytest.mark.asyncio
    async def test_fetch_uses_bulk_when_available(self):
        config = _config("eia_brent_spot", "adapter:eia:PET.RBRTE.D")
        adapter = EiaBulkAdapter(config)
        sample = (FIXTURES / "eia_brent_sample.json").read_text(encoding="utf-8")

        with patch.object(adapter, "_fetch_bulk", return_value=sample):
            raw = await adapter.fetch(None)
        assert "PET.RBRTE.D" in raw.payload
