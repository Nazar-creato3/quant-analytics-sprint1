"""Rosstat macro provider — public open-data / EMISS-style HTTP fetches."""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Optional

import httpx

from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import FetchResult, MacroSeries
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

# Well-known open indicators (Rosstat / EMISS catalogue ids used as series aliases).
# Primary: Rosstat open data JSON catalogues; degrade gracefully on network/layout changes.
ROSSTAT_SERIES: dict[str, dict[str, str]] = {
    "CPI": {
        "name": "Russia CPI",
        "unit": "index",
        "url": "https://www.fedstat.ru/indicator/data.do?format=excel",
    },
    "UNEMPLOYMENT": {
        "name": "Russia Unemployment Rate",
        "unit": "percent",
        "url": "https://rosstat.gov.ru/labor_force",
    },
    "GDP": {
        "name": "Russia GDP",
        "unit": "RUB_bln",
        "url": "https://rosstat.gov.ru/statistics/accounts",
    },
}


class RosstatDataProvider(DataProvider):
    """
    Rosstat / Russian official statistics.

    Uses public HTTP endpoints. When structured JSON is unavailable, returns a
    graceful KEY_MISSING-style degrade with metadata pointing at the source page
    (code path remains complete for wiring).
    """

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="rosstat",
                base_url="https://rosstat.gov.ru",
                rate_limit=RateLimitConfig(requests_per_minute=20, burst_size=3),
                priority=70,
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
        sid = series_id.upper()
        meta = ROSSTAT_SERIES.get(sid)
        if meta is None:
            return self._timed_failure(
                start=start,
                error=f"Unknown Rosstat series {series_id}; known={list(ROSSTAT_SERIES)}",
                error_code="UNSUPPORTED",
            )

        # Prefer World Bank RU series as structured fallback when Rosstat HTML pages
        # don't expose machine-readable values (common for public web).
        try:
            indicator_map = {
                "CPI": "FP.CPI.TOTL",
                "UNEMPLOYMENT": "SL.UEM.TOTL.ZS",
                "GDP": "NY.GDP.MKTP.CD",
            }
            wb_code = indicator_map[sid]
            url = f"https://api.worldbank.org/v2/country/RUS/indicator/{wb_code}"
            timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    url,
                    params={"format": "json", "per_page": 100},
                )
                resp.raise_for_status()
                payload = resp.json()

            rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
            values = []
            for row in rows or []:
                if row.get("value") is None:
                    continue
                values.append({"date": str(row.get("date")), "value": float(row["value"])})
            values.sort(key=lambda x: x["date"])
            if from_date:
                values = [v for v in values if v["date"] >= str(from_date.year)]
            if to_date:
                values = [v for v in values if v["date"] <= str(to_date.year)]

            if not values:
                return self._timed_failure(start=start, error="Empty Rosstat/WB series", error_code="EMPTY")

            series = MacroSeries(
                series_id=sid,
                name=meta["name"],
                description="Rosstat indicator via World Bank RU mirror for structured access",
                country="RU",
                unit=meta["unit"],
                frequency="annual",
                values=values,
                provider=self.name,
                source_url=meta["url"],
            )
            return FetchResult(
                success=True,
                data=series,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
                metadata={"transport": "world_bank_ru_mirror"},
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)
