"""Alpha Vantage provider — graceful degrade when ALPHA_VANTAGE_API_KEY missing."""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import (
    FetchResult,
    Fundamentals,
    NewsItem,
    OHLCV,
    Quote,
)
from app.services.terminal_platform.providers._helpers import parse_ts, to_decimal
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

AV_BASE = "https://www.alphavantage.co/query"

_TF_MAP = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.M30: "30min",
    Timeframe.H1: "60min",
    Timeframe.H4: "60min",
}


class AlphaVantageDataProvider(DataProvider):
    """Alpha Vantage free-tier prices / fundamentals / news sentiment."""

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="alpha_vantage",
                api_key_env="ALPHA_VANTAGE_API_KEY",
                requires_api_key=True,
                base_url=AV_BASE,
                rate_limit=RateLimitConfig(requests_per_minute=5, burst_size=1),
                priority=40,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV, DataType.QUOTE, DataType.FUNDAMENTALS, DataType.NEWS]

    async def _get(self, **params: Any) -> dict[str, Any]:
        assert self._api_key
        timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
        query = {"apikey": self._api_key, **params}
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=timeout)) as client:
            resp = await client.get(AV_BASE, params=query)
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict):
            return {}
        if data.get("Note") or data.get("Information"):
            raise RuntimeError(str(data.get("Note") or data.get("Information")))
        if data.get("Error Message"):
            raise RuntimeError(str(data["Error Message"]))
        return data

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
        if not self._api_key:
            return self._key_missing_result(start)
        try:
            if timeframe in (Timeframe.D1, Timeframe.W1, Timeframe.MN):
                fn = "TIME_SERIES_DAILY"
                key = "Time Series (Daily)"
            else:
                fn = "TIME_SERIES_INTRADAY"
                key = f"Time Series ({_TF_MAP.get(timeframe, '60min')})"
            params: dict[str, Any] = {
                "function": fn,
                "symbol": symbol.upper(),
                "outputsize": "compact",
            }
            if fn == "TIME_SERIES_INTRADAY":
                params["interval"] = _TF_MAP.get(timeframe, "60min")
            data = await self._get(**params)
            series = data.get(key) or {}
            zero = Decimal("0")
            ohlcv: list[OHLCV] = []
            for ts_str, row in sorted(series.items()):
                ts = parse_ts(ts_str)
                if ts.date() < from_date.date() or ts.date() > to_date.date():
                    continue
                ohlcv.append(
                    OHLCV(
                        symbol=symbol.upper(),
                        timeframe=timeframe.value,
                        timestamp=ts,
                        open=to_decimal(row.get("1. open")) or zero,
                        high=to_decimal(row.get("2. high")) or zero,
                        low=to_decimal(row.get("3. low")) or zero,
                        close=to_decimal(row.get("4. close")) or zero,
                        volume=to_decimal(row.get("5. volume")),
                        provider=self.name,
                    )
                )
            if not ohlcv:
                return self._timed_failure(start=start, error="Empty AV OHLCV", error_code="EMPTY")
            return FetchResult(
                success=True,
                data=ohlcv,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)

    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        if not self._api_key:
            return self._key_missing_result(start)
        try:
            data = await self._get(function="GLOBAL_QUOTE", symbol=symbol.upper())
            gq = data.get("Global Quote") or {}
            price = to_decimal(gq.get("05. price"))
            if price is None:
                return self._timed_failure(start=start, error="Empty AV quote", error_code="EMPTY")
            change_pct_raw = str(gq.get("10. change percent") or "").replace("%", "")
            change_pct = float(change_pct_raw) if change_pct_raw else None
            quote = Quote(
                symbol=symbol.upper(),
                price=price,
                timestamp=parse_ts(gq.get("07. latest trading day")),
                provider=self.name,
                change_pct=change_pct,
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
        if not self._api_key:
            return self._key_missing_result(start)
        try:
            data = await self._get(function="OVERVIEW", symbol=symbol.upper())
            if not data.get("Symbol"):
                return self._timed_failure(start=start, error="Empty AV overview", error_code="EMPTY")
            fund = Fundamentals(
                symbol=symbol.upper(),
                company_name=str(data.get("Name") or symbol),
                sector=data.get("Sector"),
                industry=data.get("Industry"),
                market_cap=to_decimal(data.get("MarketCapitalization")),
                pe_ratio=to_decimal(data.get("PERatio")),
                pb_ratio=to_decimal(data.get("PriceToBookRatio")),
                dividend_yield=to_decimal(data.get("DividendYield")),
                eps=to_decimal(data.get("EPS")),
                revenue=to_decimal(data.get("RevenueTTM")),
                provider=self.name,
                currency=data.get("Currency"),
                exchange=data.get("Exchange"),
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
        start = time.perf_counter()
        self._record_request()
        if not self._api_key:
            return self._key_missing_result(start)
        try:
            params: dict[str, Any] = {"function": "NEWS_SENTIMENT", "limit": min(limit, 50)}
            if symbols:
                # AV equity tickers only — skip crypto/index forms like BTC-USD / ^GSPC.
                clean = [
                    s.upper()
                    for s in symbols[:8]
                    if s and s.replace(".", "").isalnum() and not s.startswith("^") and "-" not in s
                ]
                if clean:
                    params["tickers"] = ",".join(clean[:5])
            data = await self._get(**params)
            feed = data.get("feed") or []
            items: list[NewsItem] = []
            for row in feed[:limit]:
                ts = row.get("time_published")
                if isinstance(ts, str) and len(ts) >= 15:
                    published = datetime.strptime(ts[:15], "%Y%m%dT%H%M%S").replace(
                        tzinfo=timezone.utc
                    )
                else:
                    published = datetime.now(timezone.utc)
                tickers = [
                    t.get("ticker")
                    for t in (row.get("ticker_sentiment") or [])
                    if isinstance(t, dict) and t.get("ticker")
                ]
                items.append(
                    NewsItem(
                        title=str(row.get("title") or ""),
                        summary=row.get("summary"),
                        source=str(row.get("source") or "alpha_vantage"),
                        url=str(row.get("url") or ""),
                        published_at=published,
                        symbols=tickers or symbols,
                        sentiment=(row.get("overall_sentiment_label") or "").lower() or None,
                        provider=self.name,
                    )
                )
            if not items:
                return self._timed_failure(start=start, error="Empty AV news", error_code="EMPTY")
            return FetchResult(
                success=True,
                data=items,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)
