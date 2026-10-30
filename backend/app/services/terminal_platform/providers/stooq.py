"""Stooq daily bars/quotes — public CSV, no key, before Yahoo in the chain."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from app.services.market_data.stooq_client import StooqClient
from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import FetchResult, OHLCV, Quote
from app.services.terminal_platform.providers._helpers import parse_ts, to_decimal
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe


class StooqDataProvider(DataProvider):
    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="stooq",
                rate_limit=RateLimitConfig(requests_per_minute=40, burst_size=8),
                priority=25,
                timeout_seconds=8.0,
            )
        )
        self._client = StooqClient()

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV, DataType.QUOTE]

    async def fetch_ohlcv(self, symbol: str, timeframe: Timeframe, from_date: datetime, to_date: datetime, **kwargs: Any) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        tf = timeframe.value if hasattr(timeframe, "value") else str(timeframe)
        try:
            bars = await self._client.get_bars(symbol, tf, from_date, to_date)
            if not bars:
                return self._timed_failure(start=start, error="Empty Stooq bars", error_code="EMPTY")
            zero = Decimal("0")
            rows = [
                OHLCV(
                    symbol=symbol.upper(),
                    timestamp=parse_ts(b.get("timestamp")),
                    open=to_decimal(b.get("open")) or zero,
                    high=to_decimal(b.get("high")) or zero,
                    low=to_decimal(b.get("low")) or zero,
                    close=to_decimal(b.get("close")) or zero,
                    volume=to_decimal(b.get("volume")),
                    timeframe=tf,
                    provider=self.name,
                )
                for b in bars
            ]
            return FetchResult(success=True, data=rows, provider=self.name, duration_ms=(time.perf_counter() - start) * 1000)
        except Exception as exc:
            return self._failure_from_exc(start, exc)

    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        try:
            raw = await self._client.get_latest_quote(symbol)
            if raw.get("price") is None:
                return self._timed_failure(start=start, error="Empty Stooq quote", error_code="EMPTY")
            quote = Quote(
                symbol=symbol.upper(),
                price=to_decimal(raw["price"]) or Decimal("0"),
                timestamp=datetime.now(timezone.utc),
                provider=self.name,
                change_pct=float(raw["change_pct"]) if raw.get("change_pct") is not None else None,
            )
            return FetchResult(success=True, data=quote, provider=self.name, duration_ms=(time.perf_counter() - start) * 1000)
        except Exception as exc:
            return self._failure_from_exc(start, exc)

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

    async def fetch_macro_series(self, series_id: str, from_date=None, to_date=None, **kwargs: Any) -> FetchResult:
        return self._unsupported(time.perf_counter(), "macro")
