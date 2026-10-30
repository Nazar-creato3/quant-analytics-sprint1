"""Generic CCXT DataProvider — parameterized by exchange id (binance, bybit, okx, …)."""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import DataQuality, FetchResult, OHLCV, Quote
from app.services.terminal_platform.providers._helpers import to_decimal
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

_TF_MAP = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
    Timeframe.W1: "1w",
    Timeframe.MN: "1M",
}


def _normalize_symbol(symbol: str) -> str | None:
    raw = (symbol or "").strip().upper().replace(" ", "")
    if not raw:
        return None
    if "/" in raw:
        return raw
    if raw.endswith("USDT"):
        base = raw[:-4]
        return f"{base}/USDT" if base else None
    if raw.endswith("USD"):
        base = raw[:-3]
        return f"{base}/USD" if base else None
    return f"{raw}/USDT"


class CCXTProvider(DataProvider):
    """Unified CCXT provider — one class, many exchanges via exchange_id."""

    def __init__(
        self,
        exchange_id: str = "binance",
        *,
        config: Optional[DataProviderConfig] = None,
        default_type: str = "spot",
    ) -> None:
        exchange_id = exchange_id.lower().strip()
        super().__init__(
            config
            or DataProviderConfig(
                name=f"ccxt_{exchange_id}",
                rate_limit=RateLimitConfig(requests_per_second=8, burst_size=4),
                priority=75,
                requires_api_key=False,
                api_key_env=f"{exchange_id.upper()}_API_KEY",
            )
        )
        self.exchange_id = exchange_id
        self.default_type = default_type

    def _exchange(self):
        import ccxt

        cls = getattr(ccxt, self.exchange_id, None)
        if cls is None:
            raise ValueError(f"unknown ccxt exchange: {self.exchange_id}")
        opts: dict[str, Any] = {"enableRateLimit": True, "options": {"defaultType": self.default_type}}
        if self._api_key:
            opts["apiKey"] = self._api_key
        if self._api_secret:
            opts["secret"] = self._api_secret
        return cls(opts)

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV, DataType.QUOTE]

    def supports(self, data_type: DataType) -> bool:
        return data_type in self.supported_data_types

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
        pair = _normalize_symbol(symbol)
        if not pair:
            return self._unsupported(start, "ohlcv")
        tf = _TF_MAP.get(timeframe, "1h")
        limit = int(kwargs.get("limit") or 200)
        try:
            exchange = await asyncio.to_thread(self._exchange)
            rows = await asyncio.to_thread(exchange.fetch_ohlcv, pair, tf, limit=min(limit, 500))
            zero = Decimal("0")
            ohlcv: list[OHLCV] = []
            for r in rows or []:
                ts = datetime.fromtimestamp(int(r[0]) / 1000.0, tz=timezone.utc)
                ohlcv.append(
                    OHLCV(
                        symbol=pair,
                        timeframe=timeframe.value,
                        timestamp=ts,
                        open=to_decimal(r[1]) or zero,
                        high=to_decimal(r[2]) or zero,
                        low=to_decimal(r[3]) or zero,
                        close=to_decimal(r[4]) or zero,
                        volume=to_decimal(r[5]),
                        provider=self.name,
                        exchange=self.exchange_id.upper(),
                    )
                )
            if not ohlcv:
                return self._timed_failure(start=start, error="No OHLCV", error_code="EMPTY")
            return FetchResult(
                success=True,
                data=ohlcv,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
                quality=DataQuality(completeness=1.0),
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)

    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        pair = _normalize_symbol(symbol)
        if not pair:
            return self._unsupported(start, "quote")
        try:
            exchange = await asyncio.to_thread(self._exchange)
            raw = await asyncio.to_thread(exchange.fetch_ticker, pair)
            price = to_decimal(raw.get("last"))
            if price is None:
                return self._timed_failure(start=start, error="No ticker", error_code="EMPTY")
            ts_ms = raw.get("timestamp")
            ts = (
                datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc)
                if ts_ms
                else datetime.now(timezone.utc)
            )
            quote = Quote(
                symbol=pair,
                price=price,
                bid=to_decimal(raw.get("bid")),
                ask=to_decimal(raw.get("ask")),
                timestamp=ts,
                provider=self.name,
                currency=pair.split("/")[-1] if "/" in pair else "USD",
                exchange=self.exchange_id.upper(),
                change_pct=float(raw["percentage"]) if raw.get("percentage") is not None else None,
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
