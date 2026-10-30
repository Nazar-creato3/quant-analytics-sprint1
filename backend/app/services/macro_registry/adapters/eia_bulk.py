"""EIA bulk/API adapter for petroleum and natural gas spot series."""
from __future__ import annotations

from pathlib import Path

import httpx

from app.core.config import settings
from app.services.macro_registry.adapters.base import IMacroAdapter, build_raw_response, http_get_with_retry
from app.services.macro_registry.eia.parser import (
    load_bulk_series,
    parse_eia_endpoint,
    parse_eia_series_payload,
)
from app.services.macro_registry.types import InternalObservation, RawResponse

EIA_API_BASE = "https://api.eia.gov/v2"


class EiaBulkAdapter(IMacroAdapter):
    """Fetch energy series from local EIA bulk zips with optional API v2 fallback."""

    async def fetch(self, client: httpx.AsyncClient) -> RawResponse:
        parsed = parse_eia_endpoint(self.config.endpoint)
        if parsed is None:
            raise ValueError(f"Unsupported EIA endpoint: {self.config.endpoint}")

        _, series_id = parsed
        bulk_payload = self._fetch_bulk(series_id)
        if bulk_payload is not None:
            return build_raw_response(self.config, bulk_payload)

        api_key = settings.EIA_API_KEY.strip()
        if not api_key:
            raise FileNotFoundError(
                f"No EIA bulk data for {series_id} and EIA_API_KEY is not configured"
            )

        url = f"{EIA_API_BASE}/seriesid/{series_id}"
        response = await http_get_with_retry(
            client,
            url,
            params={"api_key": api_key},
            timeout=45.0,
        )
        return build_raw_response(self.config, response.text)

    def normalize(self, raw: RawResponse) -> list[InternalObservation]:
        parsed = parse_eia_endpoint(self.config.endpoint)
        if parsed is None:
            return []
        _, series_id = parsed
        unit, currency = self._unit_and_currency()
        return parse_eia_series_payload(
            raw.payload,
            instrument=self.config.symbol,
            series_id=series_id,
            unit=unit,
            currency=currency,
        )

    def _fetch_bulk(self, series_id: str) -> str | None:
        bulk_root = Path(settings.EIA_BULK_PATH) if settings.EIA_BULK_PATH else None
        if bulk_root is None:
            return None
        return load_bulk_series(bulk_root, series_id=series_id)

    def _unit_and_currency(self) -> tuple[str, str]:
        if self.config.symbol == "NG_HENRY_HUB":
            return "USD/MMBtu", "USD"
        return "USD/barrel", "USD"
