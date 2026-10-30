"""CBR (Bank of Russia) macro provider — wraps SOAP key-rate helpers."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import FetchResult, MacroSeries
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe


class CbrDataProvider(DataProvider):
    """CBR key rate and FX via public SOAP / XML endpoints."""

    SERIES_ALIASES = {
        "KEY_RATE": "KEY_RATE",
        "CBR_KEY_RATE": "KEY_RATE",
        "rate_cb": "KEY_RATE",
    }

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="cbr",
                base_url="https://www.cbr.ru",
                rate_limit=RateLimitConfig(requests_per_minute=30, burst_size=5),
                priority=90,
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
        sid = self.SERIES_ALIASES.get(series_id.upper(), series_id.upper())
        if sid != "KEY_RATE":
            return self._timed_failure(
                start=start,
                error=f"CBR provider supports KEY_RATE only (got {series_id})",
                error_code="UNSUPPORTED",
            )
        try:
            from app.services.macro.indicators import (
                CBR_KEY_RATE_URL,
                CBR_SOAP_TEMPLATE,
                parse_cbr_key_rate_xml,
            )

            now = datetime.now(timezone.utc)
            end = to_date or now.date()
            begin = from_date or (end - timedelta(days=365))
            body = CBR_SOAP_TEMPLATE.format(
                from_date=f"{begin.isoformat()}T00:00:00",
                to_date=f"{end.isoformat()}T00:00:00",
            )
            timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
            async with httpx.AsyncClient(**httpx_client_kwargs(foreign=False, timeout=timeout)) as client:
                response = await client.post(
                    CBR_KEY_RATE_URL,
                    content=body.encode("utf-8"),
                    headers={
                        "Content-Type": "text/xml; charset=utf-8",
                        "SOAPAction": '"http://web.cbr.ru/KeyRateXML"',
                    },
                )
                response.raise_for_status()
                rows = parse_cbr_key_rate_xml(response.text)

            values = [
                {
                    "date": row["published_at"].date().isoformat()
                    if hasattr(row["published_at"], "date")
                    else str(row["published_at"])[:10],
                    "value": float(row["value"]),
                }
                for row in rows
            ]
            series = MacroSeries(
                series_id="KEY_RATE",
                name="CBR Key Rate",
                description="Bank of Russia key rate",
                country="RU",
                unit="percent",
                frequency="daily",
                values=values,
                provider=self.name,
                source_url=CBR_KEY_RATE_URL,
            )
            return FetchResult(
                success=True,
                data=series,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)
