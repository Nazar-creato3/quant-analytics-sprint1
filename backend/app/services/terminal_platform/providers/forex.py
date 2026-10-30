"""Classic OTC forex quotes via Twelve Data — data-only, no execution path."""
from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from app.services.market_data.forex_catalog import (
    FOREX_FEED_LABEL_RU,
    FOREX_PROVIDER_NAME,
    canonical_forex_symbol,
    is_forex_pair,
)
from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import FetchResult, OHLCV, Quote
from app.services.terminal_platform.providers._helpers import parse_ts, to_decimal
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

_TF_MAP = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "1h",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
    Timeframe.W1: "1d",
    Timeframe.MN: "1d",
}


class ForexDataProvider(DataProvider):
    """Twelve Data adapter restricted to classic forex pairs."""

    def __init__(self, config: Optional[DataProviderConfig] = None) -> None:
        super().__init__(
            config
            or DataProviderConfig(
                name="forex",
                api_key_env="TWELVEDATA_API_KEY",
                requires_api_key=True,
                rate_limit=RateLimitConfig(requests_per_minute=40, burst_size=5),
                priority=68,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV, DataType.QUOTE]

    def supports(self, data_type: DataType) -> bool:
        return data_type in self.supported_data_types

    def _client(self) -> Any:
        from app.services.market_data.http_providers import TwelveDataClient

        return TwelveDataClient()

    def _resolve(self, symbol: str) -> str | None:
        if not is_forex_pair(symbol):
            return None
        return canonical_forex_symbol(symbol)

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: datetime,
        to_date: datetime,
        **kwargs: Any,
    ) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        if not self.api_key_configured:
            return self._key_missing_result(start)
        api_sym = self._resolve(symbol)
        if not api_sym:
            return self._timed_failure(
                start=start,
                error="Symbol is not a classic forex pair",
                error_code="UNSUPPORTED",
            )
        try:
            client = self._client()
            bars = await client.get_bars(api_sym, _TF_MAP.get(timeframe, "1d"), from_date, to_date)
            if not bars:
                return self._timed_failure(start=start, error="Empty forex OHLCV", error_code="EMPTY")
            zero = Decimal("0")
            ohlcv = [
                OHLCV(
                    symbol=api_sym,
                    timeframe=timeframe.value,
                    timestamp=parse_ts(b.get("timestamp")),
                    open=to_decimal(b.get("open")) or zero,
                    high=to_decimal(b.get("high")) or zero,
                    low=to_decimal(b.get("low")) or zero,
                    close=to_decimal(b.get("close")) or zero,
                    volume=to_decimal(b.get("volume")),
                    provider=self.name,
                    exchange="OTC",
                )
                for b in bars
                if isinstance(b, dict)
            ]
            return FetchResult(
                success=True,
                data=ohlcv,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
                metadata={
                    "feed": "forex",
                    "feed_label_ru": FOREX_FEED_LABEL_RU,
                    "data_only": True,
                    "execution_enabled": False,
                    "backend": FOREX_PROVIDER_NAME,
                },
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)

    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        if not self.api_key_configured:
            return self._key_missing_result(start)
        api_sym = self._resolve(symbol)
        if not api_sym:
            return self._timed_failure(
                start=start,
                error="Symbol is not a classic forex pair",
                error_code="UNSUPPORTED",
            )
        try:
            client = self._client()
            raw = await client.get_latest_quote(api_sym)
            price = to_decimal(raw.get("price"))
            if price is None:
                return self._timed_failure(start=start, error="Empty forex quote", error_code="EMPTY")
            chg = to_decimal(raw.get("change_pct"))
            quote = Quote(
                symbol=api_sym,
                price=price,
                bid=to_decimal(raw.get("bid")),
                ask=to_decimal(raw.get("ask")),
                timestamp=parse_ts(raw.get("timestamp")),
                provider=self.name,
                exchange="OTC",
                currency=(raw.get("currency") or (api_sym.split("/")[-1] if "/" in api_sym else "USD")),
                change_pct=float(chg) if chg is not None else None,
            )
            return FetchResult(
                success=True,
                data=quote,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
                metadata={
                    "feed": "forex",
                    "feed_label_ru": FOREX_FEED_LABEL_RU,
                    "data_only": True,
                    "execution_enabled": False,
                    "backend": FOREX_PROVIDER_NAME,
                    "as_of": raw.get("timestamp"),
                },
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)

    async def fetch_macro_series(
        self,
        series_id: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        **kwargs: Any,
    ) -> FetchResult:
        return self._unsupported(time.perf_counter(), "macro")

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
