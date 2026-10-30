"""YFinance provider — wraps existing YFinanceClient patterns."""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import (
    DataQuality,
    FetchResult,
    Fundamentals,
    NewsItem,
    OHLCV,
    Quote,
)
from app.services.terminal_platform.providers._helpers import parse_ts, to_decimal
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

_TF_MAP = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "1h",
    Timeframe.H4: "1h",
    Timeframe.D1: "1d",
    Timeframe.W1: "1wk",
    Timeframe.MN: "1mo",
}


class YFinanceDataProvider(DataProvider):
    """Global equities via yfinance (no API key)."""

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="yfinance",
                rate_limit=RateLimitConfig(requests_per_minute=40, burst_size=5),
                priority=50,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV, DataType.QUOTE, DataType.FUNDAMENTALS, DataType.NEWS]

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
            from app.services.market_data.client import YFinanceClient

            client = YFinanceClient()
            bars = await client.get_bars(symbol, _TF_MAP.get(timeframe, "1d"), from_date, to_date)
            if not bars:
                return self._timed_failure(start=start, error="No yfinance OHLCV", error_code="EMPTY")
            zero = Decimal("0")
            ohlcv = [
                OHLCV(
                    symbol=symbol.upper(),
                    timeframe=timeframe.value,
                    timestamp=parse_ts(b.get("timestamp")),
                    open=to_decimal(b.get("open")) or zero,
                    high=to_decimal(b.get("high")) or zero,
                    low=to_decimal(b.get("low")) or zero,
                    close=to_decimal(b.get("close")) or zero,
                    volume=to_decimal(b.get("volume")),
                    provider=self.name,
                )
                for b in bars
            ]
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
        try:
            from app.services.market_data.client import YFinanceClient

            client = YFinanceClient()
            raw = await client.get_latest_quote(symbol)
            if not raw or raw.get("price") is None:
                return self._timed_failure(start=start, error="No yfinance quote", error_code="EMPTY")
            quote = Quote(
                symbol=symbol.upper(),
                price=to_decimal(raw["price"]) or Decimal("0"),
                bid=to_decimal(raw.get("bid")),
                ask=to_decimal(raw.get("ask")),
                timestamp=parse_ts(raw.get("timestamp")),
                provider=self.name,
                currency=raw.get("currency"),
                exchange=raw.get("exchange"),
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
            import yfinance as yf

            def _info() -> dict[str, Any]:
                t = yf.Ticker(symbol)
                return dict(getattr(t, "info", None) or {})

            info = await asyncio.to_thread(_info)
            if not info:
                return self._timed_failure(start=start, error="No yfinance fundamentals", error_code="EMPTY")
            fund = Fundamentals(
                symbol=symbol.upper(),
                company_name=str(info.get("shortName") or info.get("longName") or symbol),
                sector=info.get("sector"),
                industry=info.get("industry"),
                market_cap=to_decimal(info.get("marketCap")),
                pe_ratio=to_decimal(info.get("trailingPE") or info.get("forwardPE")),
                pb_ratio=to_decimal(info.get("priceToBook")),
                dividend_yield=to_decimal(info.get("dividendYield")),
                eps=to_decimal(info.get("trailingEps")),
                revenue=to_decimal(info.get("totalRevenue")),
                net_income=to_decimal(info.get("netIncomeToCommon")),
                debt_to_equity=to_decimal(info.get("debtToEquity")),
                provider=self.name,
                currency=info.get("currency"),
                exchange=info.get("exchange"),
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
        tickers = [s.strip() for s in (symbols or []) if s and str(s).strip()]
        if not tickers:
            tickers = ["AAPL", "MSFT", "NVDA", "SPY", "BTC-USD"]
        try:
            import yfinance as yf

            items: list[NewsItem] = []

            def _news_for(sym: str) -> list[dict[str, Any]]:
                t = yf.Ticker(sym)
                raw = getattr(t, "news", None) or []
                return list(raw) if isinstance(raw, list) else []

            for sym in tickers[:5]:
                rows = await asyncio.to_thread(_news_for, sym)
                for row in rows:
                    content = row.get("content") if isinstance(row.get("content"), dict) else {}
                    title = row.get("title") or content.get("title")
                    if not title:
                        continue
                    link = (
                        row.get("link")
                        or (content.get("clickThroughUrl") or {}).get("url")
                        or (content.get("canonicalUrl") or {}).get("url")
                        or ""
                    )
                    ts = row.get("providerPublishTime") or content.get("pubDate")
                    if isinstance(ts, (int, float)):
                        published = datetime.fromtimestamp(ts, tz=timezone.utc)
                    else:
                        published = parse_ts(ts)
                    items.append(
                        NewsItem(
                            title=str(title),
                            summary=(content.get("summary") if content else None) or row.get("summary"),
                            source=str(
                                row.get("publisher")
                                or (content.get("provider") or {}).get("displayName")
                                or "yfinance"
                            ),
                            url=str(link or f"https://finance.yahoo.com/quote/{sym}"),
                            published_at=published,
                            symbols=[sym.upper()],
                            provider=self.name,
                        )
                    )
                    if len(items) >= limit:
                        break
                if len(items) >= limit:
                    break

            if not items:
                return self._timed_failure(start=start, error="No yfinance news", error_code="EMPTY")
            return FetchResult(
                success=True,
                data=items[:limit],
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)
