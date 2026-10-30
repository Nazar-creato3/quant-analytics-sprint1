"""Energy/commodity adapter — FRED Brent + yfinance fallback (Prompt 42)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx

from app.services.macro.indicators import parse_fred_observations
from app.services.macro_registry.adapters.base import IMacroAdapter, build_raw_response
from app.services.macro_registry.fred_client import fetch_fred_series_json, parse_fred_endpoint
from app.services.macro_registry.types import InternalObservation, RawResponse


_SPOT_UNITS = {
    "BRENT_OIL": "USD/barrel",
    "WTI_OIL": "USD/barrel",
    "NG_HENRY_HUB": "USD/MMBtu",
    "GOLD": "USD/oz",
    "SILVER": "USD/oz",
    "PLATINUM": "USD/oz",
    "COPPER": "USD/lb",
}


class EnergyAdapter(IMacroAdapter):
    """Fetch oil/energy prices."""

    async def fetch(self, client: httpx.AsyncClient) -> RawResponse:
        endpoint = self.config.endpoint
        parsed = parse_fred_endpoint(endpoint)
        if parsed is not None:
            region, series_id = parsed
            payload = await fetch_fred_series_json(client, series_id, region=region)
            return build_raw_response(self.config, payload)
        if endpoint.startswith("adapter:yfinance:"):
            return await self._fetch_yfinance(client, endpoint.split(":", 2)[2])
        if endpoint.startswith("adapter:oilpriceapi:"):
            from app.services.macro_registry.spot_clients import fetch_oilpriceapi

            return build_raw_response(self.config, await fetch_oilpriceapi(client, endpoint.split(":", 2)[2]))
        if endpoint.startswith("adapter:apininjas:"):
            from app.services.macro_registry.spot_clients import fetch_api_ninjas_commodity

            return build_raw_response(
                self.config, await fetch_api_ninjas_commodity(client, endpoint.split(":", 2)[2])
            )
        raise ValueError(f"Unsupported energy endpoint: {endpoint}")

    async def _fetch_yfinance(self, client: httpx.AsyncClient, ticker: str) -> RawResponse:
        """Use yfinance library for Brent fallback (no invented REST URL)."""
        import yfinance as yf

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=30)
        hist = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if hist.empty:
            raise RuntimeError(f"yfinance returned no data for {ticker}")
        records = []
        for idx, row in hist.iterrows():
            close_val = row["Close"]
            if hasattr(close_val, "iloc"):
                close_val = close_val.iloc[0]
            records.append({"date": str(idx.date()), "close": float(close_val)})
        payload = json.dumps({"ticker": ticker, "records": records})
        return build_raw_response(self.config, payload)

    def normalize(self, raw: RawResponse) -> list[InternalObservation]:
        endpoint = self.config.endpoint
        if parse_fred_endpoint(endpoint) is not None:
            return self._normalize_fred(raw)
        if endpoint.startswith("adapter:yfinance:"):
            return self._normalize_yfinance(raw)
        if endpoint.startswith("adapter:oilpriceapi:"):
            from app.services.macro_registry.spot_clients import parse_oilpriceapi

            return self._spot_rows(parse_oilpriceapi(raw.payload))
        if endpoint.startswith("adapter:apininjas:"):
            from app.services.macro_registry.spot_clients import parse_api_ninjas_commodity

            return self._spot_rows(parse_api_ninjas_commodity(raw.payload))
        return []

    def _spot_rows(self, rows: list[dict]) -> list[InternalObservation]:
        unit = _SPOT_UNITS.get(self.config.symbol, "USD")
        return [
            InternalObservation(
                instrument=self.config.symbol,
                value=row["value"],
                currency="USD",
                unit=unit,
                release_time=row["published_at"],
                observation_time=row["published_at"],
                period=row["published_at"].strftime("%Y-%m-%d"),
            )
            for row in rows
        ]

    def _normalize_fred(self, raw: RawResponse) -> list[InternalObservation]:
        payload = json.loads(raw.payload)
        rows = parse_fred_observations("oil_brent", payload)
        observations: list[InternalObservation] = []
        for row in rows:
            published_at: datetime = row["published_at"]
            observations.append(
                InternalObservation(
                    instrument=self.config.symbol,
                    value=float(row["value"]),
                    currency="USD",
                    unit="USD/barrel",
                    release_time=published_at,
                    observation_time=published_at,
                    period=published_at.strftime("%Y-%m-%d"),
                )
            )
        return observations

    def _normalize_yfinance(self, raw: RawResponse) -> list[InternalObservation]:
        payload = json.loads(raw.payload)
        observations: list[InternalObservation] = []
        for record in payload.get("records", []):
            published_at = datetime.strptime(record["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            observations.append(
                InternalObservation(
                    instrument=self.config.symbol,
                    value=float(record["close"]),
                    currency="USD",
                    unit="USD/barrel",
                    release_time=published_at,
                    observation_time=published_at,
                    period=published_at.strftime("%Y-%m-%d"),
                )
            )
        return observations
