"""Public Binance OHLCV/quotes via direct REST (binance_spot) — no API key / no ccxt."""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import DataQuality, FetchResult, OHLCV, Quote
from app.services.terminal_platform.providers._helpers import parse_ts, to_decimal
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

# Map terminal / yfinance-style symbols → app ticker for binance_spot helpers.
_SYMBOL_MAP = {
    "BTC": "BTC-USD",
    "BTCUSD": "BTC-USD",
    "BTCUSDT": "BTC-USD",
    "BTC-USD": "BTC-USD",
    "BTC/USDT": "BTC-USD",
    "ETH": "ETH-USD",
    "ETHUSD": "ETH-USD",
    "ETHUSDT": "ETH-USD",
    "ETH-USD": "ETH-USD",
    "ETH/USDT": "ETH-USD",
}

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


def _to_app_symbol(symbol: str) -> Optional[str]:
    raw = (symbol or "").strip().upper().replace(" ", "")
    if not raw:
        return None
    if raw in _SYMBOL_MAP:
        return _SYMBOL_MAP[raw]
    if "/" in raw and raw.endswith("/USDT"):
        return f"{raw.split('/')[0]}-USD"
    if raw.endswith("USDT") and raw[:-4].isalpha():
        return f"{raw[:-4]}-USD"
    return None


class BinancePublicDataProvider(DataProvider):
    """Crypto spot OHLCV + ticker via public Binance REST (RU-direct, no proxy/ccxt)."""

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="binance_public",
                rate_limit=RateLimitConfig(requests_per_second=8, burst_size=4),
                priority=80,
                requires_api_key=False,
                timeout_seconds=2.5,
            )
        )

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
        app_sym = _to_app_symbol(symbol)
        if not app_sym:
            return self._unsupported(start, "ohlcv")
        tf = _TF_MAP.get(timeframe, "1h")
        try:
            span_sec = max(1.0, (to_date - from_date).total_seconds())
            tf_sec = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(tf, 3600)
            limit = int(min(500, max(24, span_sec / tf_sec + 5)))
        except Exception:
            limit = 96

        try:
            from app.services.market_data.binance_spot import get_crypto_bars

            bars = await get_crypto_bars(app_sym, interval=tf, limit=limit)
            if not bars:
                return self._timed_failure(start=start, error="No binance OHLCV", error_code="EMPTY")
            zero = Decimal("0")
            display = app_sym.replace("-USD", "/USDT")
            ohlcv: list[OHLCV] = []
            for b in bars:
                ts = parse_ts(b.get("timestamp"))
                if from_date.tzinfo is None:
                    from_date = from_date.replace(tzinfo=timezone.utc)
                if to_date.tzinfo is None:
                    to_date = to_date.replace(tzinfo=timezone.utc)
                if ts < from_date or ts > to_date:
                    continue
                ohlcv.append(
                    OHLCV(
                        symbol=display,
                        timeframe=timeframe.value,
                        timestamp=ts,
                        open=to_decimal(b.get("open")) or zero,
                        high=to_decimal(b.get("high")) or zero,
                        low=to_decimal(b.get("low")) or zero,
                        close=to_decimal(b.get("close")) or zero,
                        volume=to_decimal(b.get("volume")),
                        provider=self.name,
                        exchange="BINANCE",
                    )
                )
            if not ohlcv:
                # Date filter too strict — return all bars
                for b in bars:
                    ohlcv.append(
                        OHLCV(
                            symbol=display,
                            timeframe=timeframe.value,
                            timestamp=parse_ts(b.get("timestamp")),
                            open=to_decimal(b.get("open")) or zero,
                            high=to_decimal(b.get("high")) or zero,
                            low=to_decimal(b.get("low")) or zero,
                            close=to_decimal(b.get("close")) or zero,
                            volume=to_decimal(b.get("volume")),
                            provider=self.name,
                            exchange="BINANCE",
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
        app_sym = _to_app_symbol(symbol)
        if not app_sym:
            return self._unsupported(start, "quote")
        try:
            from app.services.market_data.binance_spot import get_crypto_quote

            raw = await get_crypto_quote(app_sym, force_refresh=True)
            if not raw or raw.get("price") is None:
                return self._timed_failure(start=start, error="No binance ticker", error_code="EMPTY")
            price = to_decimal(raw["price"])
            if price is None:
                return self._timed_failure(start=start, error="No binance ticker", error_code="EMPTY")
            display = app_sym.replace("-USD", "/USDT")
            quote = Quote(
                symbol=display,
                price=price,
                bid=to_decimal(raw.get("bid")),
                ask=to_decimal(raw.get("ask")),
                timestamp=parse_ts(raw.get("timestamp")),
                provider=self.name,
                currency="USDT",
                exchange="BINANCE",
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
