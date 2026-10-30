"""MOEX ISS provider — wraps existing market_data MOEX helpers."""
from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import (
    DataQuality,
    FetchResult,
    Fundamentals,
    OHLCV,
    Quote,
)
from app.services.terminal_platform.providers._helpers import parse_ts, to_decimal
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe


class MoexIssDataProvider(DataProvider):
    """MOEX ISS via existing apimoex / ISS wrappers."""

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="moex_iss",
                base_url="https://iss.moex.com/iss",
                rate_limit=RateLimitConfig(requests_per_second=5, burst_size=10),
                priority=100,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV, DataType.QUOTE, DataType.FUNDAMENTALS]

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
        try:
            from app.services.market_data.moex_iss_provider import fetch_moex_history

            days = max(1, (to_date.date() - from_date.date()).days + 1)
            bars = await fetch_moex_history(
                symbol,
                timeframe=timeframe.value if timeframe == Timeframe.D1 else "1d",
                limit=min(int(kwargs.get("limit", days)), 5000),
            )
            if not bars:
                return self._timed_failure(start=start, error="No MOEX OHLCV", error_code="EMPTY")

            zero = Decimal("0")
            ohlcv: list[OHLCV] = []
            for bar in bars:
                ts = parse_ts(bar.get("timestamp"))
                if ts.date() < from_date.date() or ts.date() > to_date.date():
                    continue
                ohlcv.append(
                    OHLCV(
                        symbol=symbol.upper(),
                        timeframe=timeframe.value,
                        timestamp=ts,
                        open=to_decimal(bar.get("open")) or zero,
                        high=to_decimal(bar.get("high")) or zero,
                        low=to_decimal(bar.get("low")) or zero,
                        close=to_decimal(bar.get("close")) or zero,
                        volume=to_decimal(bar.get("volume")),
                        provider=self.name,
                        currency="RUB",
                        exchange="MOEX",
                    )
                )
            return FetchResult(
                success=True,
                data=ohlcv,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
                quality=DataQuality(completeness=1.0 if ohlcv else 0.0),
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)

    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        try:
            from app.services.market_data.moex_iss_provider import fetch_moex_quote_enriched, is_moex_index
            from app.services.market_data.moex_spot import is_moex_ticker

            if not is_moex_ticker(symbol) and not is_moex_index(symbol):
                return self._timed_failure(
                    start=start,
                    error=f"{symbol} is not a MOEX ticker",
                    error_code="UNSUPPORTED",
                )

            raw = await fetch_moex_quote_enriched(symbol)
            if not raw or raw.get("price") is None:
                return self._timed_failure(start=start, error="No MOEX quote", error_code="EMPTY")

            quote = Quote(
                symbol=str(raw.get("ticker") or raw.get("symbol") or symbol).upper(),
                price=to_decimal(raw["price"]) or Decimal("0"),
                bid=to_decimal(raw.get("bid")),
                ask=to_decimal(raw.get("ask")),
                timestamp=parse_ts(raw.get("timestamp")),
                provider=self.name,
                currency=raw.get("currency") or "RUB",
                exchange="MOEX",
                change_pct=float(raw["change_pct"]) if raw.get("change_pct") is not None else None,
            )
            return FetchResult(
                success=True,
                data=quote,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
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
        return self._unsupported(time.perf_counter(), "macro_series")

    async def fetch_fundamentals(self, symbol: str, **kwargs: Any) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        try:
            from app.services.market_data.moex_iss_provider import fetch_moex_fundamentals

            raw = await fetch_moex_fundamentals(symbol)
            if not raw:
                return self._timed_failure(start=start, error="No MOEX fundamentals", error_code="EMPTY")
            fund = Fundamentals(
                symbol=str(raw.get("symbol") or symbol).upper(),
                company_name=str(raw.get("short_name") or symbol),
                market_cap=to_decimal(raw.get("market_cap")),
                provider=self.name,
                currency=raw.get("currency") or "RUB",
                exchange="MOEX",
            )
            return FetchResult(
                success=True,
                data=fund,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)

    async def fetch_news(
        self,
        symbols: Optional[list[str]] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        **kwargs: Any,
    ) -> FetchResult:
        return self._unsupported(time.perf_counter(), "news")
