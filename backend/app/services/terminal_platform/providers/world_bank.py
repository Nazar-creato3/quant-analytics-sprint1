"""World Bank open data provider — wraps API used by macro_registry adapter."""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Optional

import httpx

from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import FetchResult, MacroSeries
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

WB_ALIASES: dict[str, tuple[str, str]] = {
    # series_id -> (country, indicator)
    "GDP_GROWTH": ("USA", "NY.GDP.MKTP.KD.ZG"),
    "NY.GDP.MKTP.KD.ZG": ("USA", "NY.GDP.MKTP.KD.ZG"),
    "INFLATION": ("USA", "FP.CPI.TOTL.ZG"),
    "FP.CPI.TOTL.ZG": ("USA", "FP.CPI.TOTL.ZG"),
    "UNEMPLOYMENT": ("USA", "SL.UEM.TOTL.ZS"),
    "SL.UEM.TOTL.ZS": ("USA", "SL.UEM.TOTL.ZS"),
    "RU_GDP_GROWTH": ("RUS", "NY.GDP.MKTP.KD.ZG"),
}


class WorldBankDataProvider(DataProvider):
    """World Bank Indicators API — free, no key."""

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="world_bank",
                base_url="https://api.worldbank.org/v2",
                rate_limit=RateLimitConfig(requests_per_minute=60, burst_size=10),
                priority=65,
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
        sid = series_id.upper() if "." not in series_id else series_id
        country = str(kwargs.get("country") or "").upper()
        indicator = str(kwargs.get("indicator") or "")

        if not country or not indicator:
            mapped = WB_ALIASES.get(series_id.upper()) or WB_ALIASES.get(series_id)
            if mapped:
                country, indicator = mapped
            elif ":" in series_id:
                # Accept COUNTRY:INDICATOR form
                parts = series_id.split(":", 1)
                country, indicator = parts[0].upper(), parts[1]
            else:
                country = country or "USA"
                indicator = indicator or series_id

        try:
            # Prefer parser from existing World Bank module when payload arrives.
            from app.services.macro_registry.world_bank.parser import parse_api_payload

            end_year = (to_date or date.today()).year
            start_year = (from_date or date(end_year - 15, 1, 1)).year
            base = (self.config.base_url or "https://api.worldbank.org/v2").rstrip("/")
            url = f"{base}/country/{country}/indicator/{indicator}"
            timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    url,
                    params={
                        "format": "json",
                        "date": f"{start_year}:{end_year}",
                        "per_page": 20000,
                    },
                )
                resp.raise_for_status()
                text = resp.text

            observations = parse_api_payload(
                text,
                instrument=sid,
                country_code=country,
                indicator_code=indicator,
                unit="varies",
            )
            values = [
                {
                    "date": obs.period or (obs.observation_time.date().isoformat() if obs.observation_time else ""),
                    "value": float(obs.value),
                }
                for obs in observations
                if obs.value is not None
            ]
            values = [v for v in values if v["date"]]
            values.sort(key=lambda x: x["date"])

            if not values:
                return self._timed_failure(start=start, error="Empty World Bank series", error_code="EMPTY")

            series = MacroSeries(
                series_id=f"{country}:{indicator}",
                name=indicator,
                description=f"World Bank {indicator} for {country}",
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
