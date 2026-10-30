"""World Bank macro statistics adapter (API + optional bulk zip/CSV)."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.macro_registry.adapters.base import IMacroAdapter, build_raw_response, http_get_with_retry
from app.services.macro_registry.types import InternalObservation, RawResponse
from app.services.macro_registry.world_bank.parser import (
    load_bulk_from_path,
    load_bulk_xls_bytes,
    parse_api_payload,
    parse_bulk_csv_text,
    parse_world_bank_endpoint,
)
from app.services.macro_registry.world_bank.xls_parser import parse_bulk_xls_bytes

WB_API_BASE = "https://api.worldbank.org/v2"


class WorldBankAdapter(IMacroAdapter):
    """Fetch global macro indicators from World Bank API or local bulk export."""

    async def fetch(self, client: httpx.AsyncClient) -> RawResponse:
        parsed = parse_world_bank_endpoint(self.config.endpoint)
        if parsed is None:
            raise ValueError(f"Unsupported World Bank endpoint: {self.config.endpoint}")

        mode, country_code, indicator_code = parsed
        if mode == "bulk":
            payload, content_type = self._fetch_bulk(country_code, indicator_code)
            return build_raw_response(self.config, payload, content_type=content_type)

        lookback_years = 15
        end_year = datetime.now(timezone.utc).year
        start_year = end_year - lookback_years
        url = f"{WB_API_BASE}/country/{country_code}/indicator/{indicator_code}"
        response = await http_get_with_retry(
            client,
            url,
            params={
                "format": "json",
                "date": f"{start_year}:{end_year}",
                "per_page": 20000,
            },
            timeout=45.0,
        )
        return build_raw_response(self.config, response.text)

    def normalize(self, raw: RawResponse) -> list[InternalObservation]:
        parsed = parse_world_bank_endpoint(self.config.endpoint)
        if parsed is None:
            return []
        _, country_code, indicator_code = parsed
        unit = self._unit_for_symbol()

        if raw.content_type == "text/csv":
            return parse_bulk_csv_text(
                raw.payload,
                instrument=self.config.symbol,
                country_code=country_code,
                indicator_code=indicator_code,
                unit=unit,
            )
        if raw.content_type == "application/vnd.ms-excel+b64":
            xls_bytes = base64.b64decode(raw.payload.encode("ascii"))
            return parse_bulk_xls_bytes(
                xls_bytes,
                instrument=self.config.symbol,
                country_code=country_code,
                indicator_code=indicator_code,
                unit=unit,
            )
        return parse_api_payload(
            raw.payload,
            instrument=self.config.symbol,
            country_code=country_code,
            indicator_code=indicator_code,
            unit=unit,
        )

    def _fetch_bulk(self, country_code: str, indicator_code: str) -> tuple[str, str]:
        bulk_root = Path(settings.WORLD_BANK_BULK_PATH) if settings.WORLD_BANK_BULK_PATH else None
        if bulk_root is None:
            raise FileNotFoundError("WORLD_BANK_BULK_PATH is not configured")

        xls_bytes = load_bulk_xls_bytes(
            bulk_root,
            country_code=country_code,
            indicator_code=indicator_code,
        )
        if xls_bytes is not None:
            encoded = base64.b64encode(xls_bytes).decode("ascii")
            return encoded, "application/vnd.ms-excel+b64"

        loaded = load_bulk_from_path(
            bulk_root,
            country_code=country_code,
            indicator_code=indicator_code,
        )
        if loaded is None:
            raise FileNotFoundError(
                f"No World Bank bulk CSV/xls found for {country_code}/{indicator_code} under {bulk_root}"
            )
        return loaded

    def _unit_for_symbol(self) -> str:
        if "CURRENT_ACCOUNT" in self.config.symbol:
            return "% of GDP"
        if "INFLATION" in self.config.symbol or "GDP" in self.config.symbol:
            return "%"
        return "index_points"
