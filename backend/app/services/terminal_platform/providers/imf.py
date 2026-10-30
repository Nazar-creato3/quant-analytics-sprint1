"""IMF DataMapper / SDMX-lite macro provider."""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Optional

import httpx

from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import FetchResult, MacroSeries
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

# IMF DataMapper indicator codes (free, no key).
IMF_ALIASES: dict[str, str] = {
    "GDP_GROWTH": "NGDP_RPCH",
    "NGDP_RPCH": "NGDP_RPCH",
    "INFLATION": "PCPIPCH",
    "PCPIPCH": "PCPIPCH",
    "UNEMPLOYMENT": "LUR",
    "LUR": "LUR",
    "CURRENT_ACCOUNT": "BCA_NGDPD",
}


class ImfDataProvider(DataProvider):
    """IMF public DataMapper API — no API key required."""

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="imf",
                base_url="https://www.imf.org/external/datamapper/api/v1",
                rate_limit=RateLimitConfig(requests_per_minute=30, burst_size=5),
                priority=60,
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
        indicator = IMF_ALIASES.get(series_id.upper(), series_id.upper())
        country = str(kwargs.get("country") or "US").upper()
        try:
            base = (self.config.base_url or "https://www.imf.org/external/datamapper/api/v1").rstrip("/")
            url = f"{base}/{indicator}"
            timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()

            values_by_country = (payload.get("values") or {}).get(indicator) or {}
            country_series = values_by_country.get(country) or values_by_country.get(country[:2])
            if not country_series and values_by_country:
                # Fall back to first available country if requested missing.
                country_series = next(iter(values_by_country.values()))
                country = next(iter(values_by_country.keys()))

            if not isinstance(country_series, dict):
                return self._timed_failure(start=start, error="Empty IMF series", error_code="EMPTY")

            values = []
            for year, val in sorted(country_series.items()):
                if val is None:
                    continue
                if from_date and int(year) < from_date.year:
                    continue
                if to_date and int(year) > to_date.year:
                    continue
                values.append({"date": str(year), "value": float(val)})

            if not values:
                return self._timed_failure(start=start, error="Empty IMF series after filters", error_code="EMPTY")

            series = MacroSeries(
                series_id=indicator,
                name=indicator,
                description=f"IMF DataMapper {indicator}",
                country=country,
                unit="varies",
                frequency="annual",
                values=values,
                provider=self.name,
                source_url=url,
            )
            return FetchResult(
                success=True,
                data=series,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)
