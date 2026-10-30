"""FMP provider — wraps existing fmp_provider + quote/news HTTP."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import (
    CalendarEvent,
    FetchResult,
    Fundamentals,
    NewsItem,
    OHLCV,
    Quote,
)
from app.services.terminal_platform.providers._helpers import parse_ts, to_decimal
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

FMP_BASE = "https://financialmodelingprep.com/api/v3"
FMP_STABLE_CALENDAR = "https://financialmodelingprep.com/stable/economic-calendar"


class FmpDataProvider(DataProvider):
    """Financial Modeling Prep — fundamentals primary; quote/OHLCV/news when keyed."""

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="fmp",
                api_key_env="FMP_API_KEY",
                requires_api_key=True,
                base_url=FMP_BASE,
                rate_limit=RateLimitConfig(requests_per_minute=60, burst_size=10),
                priority=45,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.OHLCV, DataType.QUOTE, DataType.FUNDAMENTALS, DataType.NEWS]

    async def _get(self, path: str, **params: Any) -> Any:
        if not self._api_key:
            return None
        timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
        query = {"apikey": self._api_key, **params}
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=timeout)) as client:
            resp = await client.get(f"{FMP_BASE}{path}", params=query)
            resp.raise_for_status()
            return resp.json()

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
            data = await self._get_historical(symbol, from_date, to_date)
            hist = data.get("historical") if isinstance(data, dict) else None
            if not hist:
                return self._timed_failure(start=start, error="Empty FMP OHLCV", error_code="EMPTY")
            zero = Decimal("0")
            ohlcv = [
                OHLCV(
                    symbol=symbol.upper(),
                    timeframe=timeframe.value,
                    timestamp=parse_ts(row.get("date")),
                    open=to_decimal(row.get("open")) or zero,
                    high=to_decimal(row.get("high")) or zero,
                    low=to_decimal(row.get("low")) or zero,
                    close=to_decimal(row.get("close")) or zero,
                    volume=to_decimal(row.get("volume")),
                    provider=self.name,
                )
                for row in reversed(hist)
            ]
            return FetchResult(
                success=True,
                data=ohlcv,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)

    async def _get_historical(
        self, symbol: str, from_date: datetime, to_date: datetime
    ) -> dict[str, Any]:
        if not self._api_key:
            return {}
        timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=timeout)) as client:
            resp = await client.get(
                f"{FMP_BASE}/historical-price-full/{symbol.upper()}",
                params={
                    "apikey": self._api_key,
                    "from": from_date.date().isoformat(),
                    "to": to_date.date().isoformat(),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}

    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        if not self._api_key:
            return self._key_missing_result(start)
        try:
            data = await self._get(f"/quote/{symbol.upper()}")
            row = data[0] if isinstance(data, list) and data else {}
            price = to_decimal(row.get("price"))
            if price is None:
                return self._timed_failure(start=start, error="Empty FMP quote", error_code="EMPTY")
            quote = Quote(
                symbol=symbol.upper(),
                price=price,
                bid=to_decimal(row.get("bid")),
                ask=to_decimal(row.get("ask")),
                timestamp=datetime.now(timezone.utc),
                provider=self.name,
                currency="USD",
                exchange=row.get("exchange"),
                change_pct=float(row["changesPercentage"])
                if row.get("changesPercentage") is not None
                else None,
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
            from app.services.market_data.fmp_provider import fetch_fmp_fundamentals

            raw = await fetch_fmp_fundamentals(symbol)
            if not raw:
                return self._timed_failure(start=start, error="Empty FMP fundamentals", error_code="EMPTY")
            fund = Fundamentals(
                symbol=str(raw.get("symbol") or symbol).upper(),
                company_name=str(raw.get("short_name") or symbol),
                sector=raw.get("sector"),
                industry=raw.get("industry"),
                market_cap=to_decimal(raw.get("market_cap")),
                pe_ratio=to_decimal(raw.get("pe_ratio")),
                pb_ratio=to_decimal(raw.get("price_to_book")),
                dividend_yield=to_decimal(raw.get("dividend_yield")),
                eps=to_decimal(raw.get("eps")),
                revenue=to_decimal(raw.get("revenue")),
                net_income=to_decimal(raw.get("net_income")),
                debt_to_equity=to_decimal(raw.get("debt_to_equity")),
                provider=self.name,
                currency=raw.get("currency"),
                exchange=raw.get("exchange"),
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
            path = "/stock_news"
            params: dict[str, Any] = {"limit": min(limit, 50)}
            if symbols:
                params["tickers"] = ",".join(s.upper() for s in symbols[:5])
            data = await self._get(path, **params)
            if not isinstance(data, list) or not data:
                return self._timed_failure(start=start, error="Empty FMP news", error_code="EMPTY")
            items = [
                NewsItem(
                    title=str(row.get("title") or ""),
                    summary=row.get("text"),
                    source=str(row.get("site") or "fmp"),
                    url=str(row.get("url") or ""),
                    published_at=parse_ts(row.get("publishedDate")),
                    symbols=[row["symbol"]] if row.get("symbol") else symbols,
                    provider=self.name,
                )
                for row in data[:limit]
                if row.get("title")
            ]
            return FetchResult(
                success=True,
                data=items,
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)

    @staticmethod
    def _impact_to_importance(raw: Any) -> Optional[str]:
        text = str(raw or "").strip().lower()
        if not text:
            return None
        if text.startswith("h"):
            return "high"
        if text.startswith("m"):
            return "medium"
        if text.startswith("l"):
            return "low"
        return text if text in {"high", "medium", "low"} else None

    async def fetch_economic_calendar(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = 50,
        **kwargs: Any,
    ) -> FetchResult:
        """FMP stable `/economic-calendar` — upcoming macro releases."""
        start = time.perf_counter()
        self._record_request()
        if not self._api_key:
            return self._key_missing_result(start)
        try:
            today = datetime.now(timezone.utc).date()
            begin = from_date or today
            end = to_date or (today + timedelta(days=14))
            timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
            async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=timeout)) as client:
                resp = await client.get(
                    FMP_STABLE_CALENDAR,
                    params={
                        "apikey": self._api_key,
                        "from": begin.isoformat(),
                        "to": end.isoformat(),
                    },
                )
                if resp.status_code == 402:
                    return self._timed_failure(
                        start=start,
                        error="FMP economic calendar requires paid tier (402)",
                        error_code="TIER_REQUIRED",
                    )
                if resp.status_code == 403:
                    body = resp.text[:200]
                    if "legacy" in body.lower():
                        return self._timed_failure(
                            start=start,
                            error="FMP legacy calendar endpoint retired",
                            error_code="LEGACY_ENDPOINT",
                        )
                resp.raise_for_status()
                data = resp.json()
            if isinstance(data, dict) and data.get("Error Message"):
                msg = str(data["Error Message"])
                code = "TIER_REQUIRED" if "subscription" in msg.lower() or "premium" in msg.lower() else "PROVIDER_ERROR"
                return self._timed_failure(start=start, error=msg[:200], error_code=code)
            if not isinstance(data, list) or not data:
                return self._timed_failure(
                    start=start, error="Empty FMP economic calendar", error_code="EMPTY"
                )
            events: list[CalendarEvent] = []
            for i, row in enumerate(data[: max(limit, 1)]):
                if not isinstance(row, dict):
                    continue
                title = str(row.get("event") or row.get("title") or "").strip()
                if not title:
                    continue
                when = parse_ts(row.get("date") or row.get("releaseDate"))
                country = row.get("country") or row.get("currency")
                expected = row.get("estimate")
                actual = row.get("actual")
                previous = row.get("previous")
                events.append(
                    CalendarEvent(
                        id=f"fmp-{i}-{when.isoformat()}-{title[:40]}",
                        title=title,
                        when=when,
                        region=str(country).upper() if country else None,
                        importance=self._impact_to_importance(row.get("impact")),
                        expected=None if expected is None else str(expected),
                        actual=None if actual is None else str(actual),
                        previous=None if previous is None else str(previous),
                        provider=self.name,
                        currency=str(row["currency"]) if row.get("currency") else None,
                    )
                )
            if not events:
                return self._timed_failure(
                    start=start, error="No calendar events parsed", error_code="EMPTY"
                )
            return FetchResult(
                success=True,
                data=events[:limit],
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)
