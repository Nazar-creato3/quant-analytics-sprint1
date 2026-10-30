"""Marketstack EOD provider — Asia/Europe curated instruments (data-only)."""
from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.market_data.marketstack_catalog import (
    EOD_FEED_LABEL_RU,
    is_marketstack_eligible,
    resolve_marketstack_symbol,
)
from app.services.terminal_platform.models import FetchResult, OHLCV, Quote
from app.services.terminal_platform.providers._helpers import parse_ts, to_decimal
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

_TF_MAP = {
    Timeframe.M1: "1d",
    Timeframe.M5: "1d",
    Timeframe.M15: "1d",
    Timeframe.M30: "1d",
    Timeframe.H1: "1d",
    Timeframe.H4: "1d",
    Timeframe.D1: "1d",
    Timeframe.W1: "1d",
    Timeframe.MN: "1d",
}


class MarketstackProvider(DataProvider):
    """
    Marketstack free-tier EOD adapter for Asia/Europe equities.

    Only serves symbols in the curated catalog or with known intl exchange suffixes.
    All quotes are end-of-previous-session — not live.
    """

    def __init__(self, config: Optional[DataProviderConfig] = None) -> None:
        super().__init__(
            config
            or DataProviderConfig(
                name="marketstack",
                api_key_env="MARKETSTACK_API_KEY",
                requires_api_key=True,
                rate_limit=RateLimitConfig(requests_per_minute=40, burst_size=5),
                priority=72,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV, DataType.QUOTE]

    def supports(self, data_type: DataType) -> bool:
        return data_type in self.supported_data_types

    def _client(self) -> Any:
        from app.services.market_data.http_providers import MarketStackClient

        return MarketStackClient()

    def _resolve(self, symbol: str) -> str | None:
        return resolve_marketstack_symbol(symbol)

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
        if not api_sym or not is_marketstack_eligible(api_sym):
            return self._timed_failure(
                start=start,
                error="Symbol not in Marketstack Asia/Europe catalog",
                error_code="UNSUPPORTED",
            )
        try:
            client = self._client()
            bars = await client.get_bars(api_sym, _TF_MAP.get(timeframe, "1d"), from_date, to_date)
            if not bars:
                return self._timed_failure(start=start, error="Empty Marketstack OHLCV", error_code="EMPTY")
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
                    exchange="EOD",
                )
                for b in bars
                if isinstance(b, dict)
            ]
            return FetchResult(
                success=True,
                data=ohlcv,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
                metadata={"feed": "eod", "feed_label_ru": EOD_FEED_LABEL_RU},
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)

    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        if not self.api_key_configured:
            return self._key_missing_result(start)
        api_sym = self._resolve(symbol)
        if not api_sym or not is_marketstack_eligible(api_sym):
            return self._timed_failure(
                start=start,
                error="Symbol not in Marketstack Asia/Europe catalog",
                error_code="UNSUPPORTED",
            )
        try:
            client = self._client()
            raw = await client.get_latest_quote(api_sym)
            price = to_decimal(raw.get("price"))
            if price is None:
                return self._timed_failure(start=start, error="Empty Marketstack quote", error_code="EMPTY")
            from app.services.instrument.asset_class import display_currency
            from app.services.market_data.marketstack_catalog import lookup_marketstack_instrument

            inst = lookup_marketstack_instrument(api_sym)
            currency = display_currency(
                api_sym,
                provider_currency=raw.get("currency") or (inst.currency if inst else None),
            )
            quote = Quote(
                symbol=api_sym,
                price=price,
                bid=None,
                ask=None,
                timestamp=parse_ts(raw.get("timestamp")),
                provider=self.name,
                exchange=(inst.exchange if inst else None) or "EOD",
                currency=currency,
                change_pct=None,
            )
            return FetchResult(
                success=True,
                data=quote,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
                metadata={
                    "feed": "eod",
                    "feed_label_ru": EOD_FEED_LABEL_RU,
                    "data_only": True,
                    "execution_enabled": False,
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


# Backward-compatible alias used by keyed_market imports.
MarketStackDataProvider = MarketstackProvider
