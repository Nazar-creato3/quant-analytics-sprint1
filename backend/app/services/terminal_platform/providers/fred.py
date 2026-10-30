"""FRED provider — wraps macro_registry.fred_client."""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import FetchResult, MacroSeries
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

ALIAS_TO_FRED: dict[str, str] = {
    "FEDFUNDS": "FEDFUNDS",
    "FED_FUNDS_RATE": "FEDFUNDS",
    "CPI": "CPIAUCSL",
    "US_CPI": "CPIAUCSL",
    "UNRATE": "UNRATE",
    "US_UNEMPLOYMENT": "UNRATE",
    "VIX": "VIXCLS",
    "DGS10": "DGS10",
    "GOV_10Y": "DGS10",
    "HY_OAS": "BAMLH0A0HYM2",
}


class FredDataProvider(DataProvider):
    """US / Canada macro series via FRED API (requires FRED_API_KEY)."""

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="fred",
                api_key_env="FRED_API_KEY",
                requires_api_key=True,
                base_url="https://api.stlouisfed.org/fred",
                rate_limit=RateLimitConfig(requests_per_minute=100, burst_size=10),
                priority=95,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.MACRO_SERIES]

    async def fetch_ohlcv(self, symbol: str, timeframe: Timeframe, from_date: datetime, to_date: datetime, **kwargs: Any) -> FetchResult:
        return self._unsupported(time.perf_counter(), "ohlcv")

    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        return self._unsupported(time.perf_counter(), "quote")

    async def fetch_fundamentals(self, symbol: str, **kwargs: Any) -> FetchResult:
        return self._unsupported(time.perf_counter(), "fundamentals")

    async def fetch_news(
        self,
        symbols: Optional[list[str]] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        **kwargs: Any,
    ) -> FetchResult:
        return self._unsupported(time.perf_counter(), "news")

    async def fetch_macro_series(
        self,
        series_id: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        **kwargs: Any,
    ) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        if not self._api_key:
            return self._key_missing_result(start)

        fred_id = ALIAS_TO_FRED.get(series_id.upper(), series_id.upper())
        region = str(kwargs.get("region") or "us")
        try:
            from app.services.macro_registry.fred_client import fetch_fred_series_json

            lookback = 3650
            if from_date:
                lookback = max(30, (datetime.now(timezone.utc).date() - from_date).days + 1)

            timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
            async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=timeout)) as client:
                payload_text = await fetch_fred_series_json(
                    client,
                    fred_id,
                    region=region if region in ("us", "canada") else "us",
                    lookback_days=lookback,
                )
            payload = json.loads(payload_text)
            observations = payload.get("observations") or []
            values = []
            for obs in observations:
                if obs.get("value") in (None, "."):
                    continue
                d = obs.get("date")
                if from_date and d and d < from_date.isoformat():
                    continue
                if to_date and d and d > to_date.isoformat():
                    continue
                values.append({"date": d, "value": float(obs["value"])})

            if not values:
                return self._timed_failure(start=start, error="Empty FRED series", error_code="EMPTY")

            series = MacroSeries(
                series_id=fred_id,
                name=fred_id,
                description=f"FRED series {fred_id}",
                country="US" if region != "canada" else "CA",
                unit="varies",
                frequency="varies",
                values=values,
                provider=self.name,
                source_url=f"https://fred.stlouisfed.org/series/{fred_id}",
            )
            return FetchResult(
                success=True,
                data=series,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except RuntimeError as exc:
            # Missing regional key from fred_client.resolve_fred_api_key
            return self._timed_failure(start=start, error=str(exc), error_code="KEY_MISSING")
        except Exception as exc:
            return self._failure_from_exc(start, exc)
