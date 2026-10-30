"""Central bank rate adapter — CBR SOAP, FRED (US/CA), BoC Valet (Prompt 42)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from app.services.macro.indicators import (
    CBR_KEY_RATE_URL,
    CBR_SOAP_TEMPLATE,
    parse_cbr_key_rate_xml,
    parse_fred_observations,
)
from app.services.macro_registry.adapters.base import IMacroAdapter, build_raw_response, http_get_with_retry
from app.services.macro_registry.boc_client import BOC_VALET_BASE, parse_boc_valet_observations
from app.services.macro_registry.fred_client import fetch_fred_series_json, parse_fred_endpoint
from app.services.macro_registry.types import InternalObservation, RawResponse


class CentralBankAdapter(IMacroAdapter):
    """Fetch central bank policy rates."""

    async def fetch(self, client: httpx.AsyncClient) -> RawResponse:
        endpoint = self.config.endpoint
        if endpoint == "adapter:cbr_soap":
            return await self._fetch_cbr(client)
        if endpoint.startswith("adapter:boc_valet:"):
            series_id = endpoint.split(":", 2)[2]
            return await self._fetch_boc_valet(client, series_id)
        if endpoint.startswith("adapter:riksbank:"):
            from app.services.macro_registry.spot_clients import fetch_riksbank_series

            series_id = endpoint.split(":", 2)[2]
            payload = await fetch_riksbank_series(client, series_id)
            return build_raw_response(self.config, payload)
        parsed = parse_fred_endpoint(endpoint)
        if parsed is not None:
            region, series_id = parsed
            return await self._fetch_fred(client, series_id, region=region)
        raise ValueError(f"Unsupported central bank endpoint: {endpoint}")

    async def _fetch_cbr(self, client: httpx.AsyncClient) -> RawResponse:
        now = datetime.now(timezone.utc)
        from_date = (now - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00")
        to_date = now.strftime("%Y-%m-%dT00:00:00")
        body = CBR_SOAP_TEMPLATE.format(from_date=from_date, to_date=to_date)
        response = await http_get_with_retry(
            client,
            CBR_KEY_RATE_URL,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": '"http://web.cbr.ru/KeyRateXML"',
            },
            content=body.encode("utf-8"),
        )
        return build_raw_response(
            self.config,
            response.text,
            content_type="text/xml",
            http_status=response.status_code,
        )

    async def _fetch_boc_valet(self, client: httpx.AsyncClient, series_id: str) -> RawResponse:
        start = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        url = f"{BOC_VALET_BASE}/{series_id}/json"
        response = await http_get_with_retry(client, url, params={"start_date": start})
        return build_raw_response(self.config, response.text, http_status=response.status_code)

    async def _fetch_fred(
        self,
        client: httpx.AsyncClient,
        series_id: str,
        *,
        region: str,
    ) -> RawResponse:
        payload = await fetch_fred_series_json(client, series_id, region=region, lookback_days=365)
        return build_raw_response(self.config, payload)

    def normalize(self, raw: RawResponse) -> list[InternalObservation]:
        endpoint = self.config.endpoint
        if endpoint == "adapter:cbr_soap":
            return self._normalize_cbr(raw)
        if endpoint.startswith("adapter:boc_valet:"):
            series_id = endpoint.split(":", 2)[2]
            return self._normalize_boc_valet(raw, series_id)
        if endpoint.startswith("adapter:riksbank:"):
            return self._normalize_riksbank(raw)
        parsed = parse_fred_endpoint(endpoint)
        if parsed is not None:
            _, series_id = parsed
            return self._normalize_fred(raw, series_id)
        return []

    def _normalize_cbr(self, raw: RawResponse) -> list[InternalObservation]:
        rows = parse_cbr_key_rate_xml(raw.payload)
        observations: list[InternalObservation] = []
        for row in rows:
            published_at: datetime = row["published_at"]
            observations.append(
                InternalObservation(
                    instrument=self.config.symbol,
                    value=float(row["value"]),
                    currency="RUB",
                    unit="%",
                    release_time=published_at,
                    observation_time=published_at,
                    period=published_at.strftime("%Y-%m"),
                )
            )
        return observations

    def _normalize_riksbank(self, raw: RawResponse) -> list[InternalObservation]:
        from app.services.macro_registry.spot_clients import parse_riksbank_observations

        return [
            InternalObservation(
                instrument=self.config.symbol,
                value=row["value"],
                currency="SEK",
                unit="%",
                release_time=row["published_at"],
                observation_time=row["published_at"],
                period=row["published_at"].strftime("%Y-%m-%d"),
            )
            for row in parse_riksbank_observations(raw.payload)
        ]

    def _normalize_boc_valet(self, raw: RawResponse, series_id: str) -> list[InternalObservation]:
        import json

        payload = json.loads(raw.payload)
        rows = parse_boc_valet_observations(payload, series_id=series_id)
        observations: list[InternalObservation] = []
        for row in rows:
            published_at: datetime = row["published_at"]
            observations.append(
                InternalObservation(
                    instrument=self.config.symbol,
                    value=float(row["value"]),
                    currency="CAD",
                    unit="%",
                    release_time=published_at,
                    observation_time=published_at,
                    period=published_at.strftime("%Y-%m"),
                )
            )
        return observations

    def _normalize_fred(self, raw: RawResponse, series_id: str) -> list[InternalObservation]:
        import json

        payload = json.loads(raw.payload)
        code = self.config.symbol.lower()
        rows = parse_fred_observations(code, payload)
        prefix_ccy = {"BOC_": "CAD", "CA_": "CAD", "ECB_": "EUR", "BOE_": "GBP", "BOJ_": "JPY", "PBOC_": "CNY"}
        currency = next((c for p, c in prefix_ccy.items() if self.config.symbol.startswith(p)), "USD")
        period_fmt = "%Y-%m-%d" if self.config.category == "credit" else "%Y-%m"
        observations: list[InternalObservation] = []
        for row in rows:
            published_at: datetime = row["published_at"]
            observations.append(
                InternalObservation(
                    instrument=self.config.symbol,
                    value=float(row["value"]),
                    currency=currency,
                    unit="%",
                    release_time=published_at,
                    observation_time=published_at,
                    period=published_at.strftime(period_fmt),
                )
            )
        return observations
