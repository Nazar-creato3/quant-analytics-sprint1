"""Inflation/employment statistics adapter — FRED US/Canada (Prompt 42)."""
from __future__ import annotations

import httpx

from app.services.macro.indicators import parse_fred_observations
from app.services.macro_registry.adapters.base import IMacroAdapter, build_raw_response
from app.services.macro_registry.fred_client import fetch_fred_series_json, parse_fred_endpoint
from app.services.macro_registry.types import InternalObservation, RawResponse


class MacroStatisticsAdapter(IMacroAdapter):
    """Fetch inflation and employment series from FRED."""

    async def fetch(self, client: httpx.AsyncClient) -> RawResponse:
        parsed = parse_fred_endpoint(self.config.endpoint)
        if parsed is None:
            raise ValueError(f"Unsupported statistics endpoint: {self.config.endpoint}")
        region, series_id = parsed
        lookback = 730 if self.config.category in ("inflation", "employment") else 365
        payload = await fetch_fred_series_json(
            client,
            series_id,
            region=region,
            lookback_days=lookback,
        )
        return build_raw_response(self.config, payload)

    def normalize(self, raw: RawResponse) -> list[InternalObservation]:
        import json
        from datetime import datetime

        payload = json.loads(raw.payload)
        code = self.config.symbol.lower()
        rows = parse_fred_observations(code, payload)
        unit = "%" if self.config.category in ("inflation", "employment") else "index_points"
        if self.config.category == "fx":
            currency = None
            unit = "CAD/USD"
        elif self.config.symbol.startswith(("CA_", "USDCAD")):
            currency = "CAD"
        else:
            currency = "USD"
        observations: list[InternalObservation] = []
        period_fmt = "%Y-%m-%d" if self.config.category in ("fx", "volatility_index") else "%Y-%m"
        for row in rows:
            published_at: datetime = row["published_at"]
            observations.append(
                InternalObservation(
                    instrument=self.config.symbol,
                    value=float(row["value"]),
                    currency=currency,
                    unit=unit,
                    release_time=published_at,
                    observation_time=published_at,
                    period=published_at.strftime(period_fmt),
                )
            )
        return observations
