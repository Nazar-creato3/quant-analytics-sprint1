"""Terminal ProviderRouter adapters for Alpaca/Polygon/TwelveData/Tiingo/MarketStack/Finnhub/CoinGecko."""
from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Optional

from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import FetchResult, NewsItem, OHLCV, Quote
from app.services.terminal_platform.providers._helpers import parse_ts, to_decimal
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

_TF_MAP = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
    Timeframe.W1: "1d",
    Timeframe.MN: "1d",
}


class _HttpMarketDataProvider(DataProvider):
    """Thin terminal adapter around a market_data HTTP/API client factory."""

    def __init__(
        self,
        *,
        name: str,
        api_key_env: Optional[str],
        api_secret_env: Optional[str] = None,
        client_factory: Callable[[], Any],
        requires_api_key: bool = True,
        priority: int = 70,
        rpm: int = 60,
        crypto_only: bool = False,
        supports_news: bool = False,
    ):
        self._client_factory = client_factory
        self._crypto_only = crypto_only
        self._supports_news = supports_news
        super().__init__(
            DataProviderConfig(
                name=name,
                api_key_env=api_key_env,
                api_secret_env=api_secret_env,
                requires_api_key=requires_api_key,
                rate_limit=RateLimitConfig(requests_per_minute=rpm, burst_size=5),
                priority=priority,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        types = [DataType.OHLCV, DataType.QUOTE]
        if self._supports_news:
            types.append(DataType.NEWS)
        return types

    def _client(self) -> Any:
        return self._client_factory()

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
        if self.config.requires_api_key and not self._api_key:
            # Alpaca needs both key+secret; api_key_configured covers secret via env reload.
            if not self.api_key_configured:
                return self._key_missing_result(start)
        if self._crypto_only:
            from app.services.market_data.binance_spot import is_crypto_ticker

            if not is_crypto_ticker(symbol):
                return self._timed_failure(
                    start=start,
                    error="CoinGecko only for crypto symbols",
                    error_code="UNSUPPORTED",
                )
        try:
            client = self._client()
            bars = await client.get_bars(symbol, _TF_MAP.get(timeframe, "1d"), from_date, to_date)
            if not bars:
                return self._timed_failure(start=start, error=f"Empty {self.name} OHLCV", error_code="EMPTY")
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
                if isinstance(b, dict)
            ]
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
        if self.config.requires_api_key and not self.api_key_configured:
            return self._key_missing_result(start)
        if self._crypto_only:
            from app.services.market_data.binance_spot import is_crypto_ticker

            if not is_crypto_ticker(symbol):
                return self._timed_failure(
                    start=start,
                    error="CoinGecko only for crypto symbols",
                    error_code="UNSUPPORTED",
                )
        try:
            client = self._client()
            raw = await client.get_latest_quote(symbol)
            if not raw or raw.get("price") is None:
                return self._timed_failure(start=start, error=f"Empty {self.name} quote", error_code="EMPTY")
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
        return self._unsupported(time.perf_counter(), "macro")

    async def fetch_fundamentals(self, symbol: str, **kwargs: Any) -> FetchResult:
        return self._unsupported(time.perf_counter(), "fundamentals")

    async def fetch_news(
        self,
        query: Optional[str] = None,
        symbols: Optional[list[str]] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        **kwargs: Any,
    ) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        if not self._supports_news:
            return self._unsupported(start, "news")
        if self.config.requires_api_key and not self.api_key_configured:
            return self._key_missing_result(start)
        try:
            client = self._client()
            get_news = getattr(client, "get_news", None)
            if get_news is None:
                return self._unsupported(start, "news")
            rows = await get_news(
                symbols=symbols,
                limit=limit,
                from_date=from_date,
                to_date=to_date,
            )
            if not rows:
                return self._timed_failure(
                    start=start, error=f"Empty {self.name} news", error_code="EMPTY"
                )
            items: list[NewsItem] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "").strip()
                if not title:
                    continue
                items.append(
                    NewsItem(
                        title=title,
                        summary=row.get("summary"),
                        source=str(row.get("source") or self.name),
                        url=str(row.get("url") or ""),
                        published_at=parse_ts(row.get("published_at")),
                        symbols=row.get("symbols") if isinstance(row.get("symbols"), list) else symbols,
                        provider=self.name,
                    )
                )
            if not items:
                return self._timed_failure(
                    start=start, error=f"Empty {self.name} news", error_code="EMPTY"
                )
            return FetchResult(
                success=True,
                data=items[:limit],
                provider=self.name,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return self._failure_from_exc(start, exc)


class AlpacaDataProvider(_HttpMarketDataProvider):
    def __init__(self) -> None:
        from app.services.market_data.client import AlpacaClient

        super().__init__(
            name="alpaca",
            api_key_env="ALPACA_API_KEY",
            api_secret_env="ALPACA_SECRET_KEY",
            client_factory=AlpacaClient,
            priority=90,
            rpm=120,
        )


class PolygonDataProvider(_HttpMarketDataProvider):
    def __init__(self) -> None:
        from app.services.market_data.client import PolygonClient

        super().__init__(
            name="polygon",
            api_key_env="POLYGON_API_KEY",
            client_factory=PolygonClient,
            priority=85,
            rpm=60,
            supports_news=True,
        )


class TwelveDataDataProvider(_HttpMarketDataProvider):
    def __init__(self) -> None:
        from app.services.market_data.http_providers import TwelveDataClient

        super().__init__(
            name="twelvedata",
            api_key_env="TWELVEDATA_API_KEY",
            client_factory=TwelveDataClient,
            priority=80,
            rpm=40,
        )


class TiingoDataProvider(_HttpMarketDataProvider):
    def __init__(self) -> None:
        from app.services.market_data.http_providers import TiingoClient

        super().__init__(
            name="tiingo",
            api_key_env="TIINGO_API_KEY",
            client_factory=TiingoClient,
            priority=75,
            rpm=40,
            supports_news=True,
        )


class FinnhubDataProvider(_HttpMarketDataProvider):
    def __init__(self) -> None:
        from app.services.market_data.http_providers import FinnhubMarketClient

        super().__init__(
            name="finnhub",
            api_key_env="FINNHUB_API_KEY",
            client_factory=FinnhubMarketClient,
            priority=65,
            rpm=40,
            supports_news=True,
        )


class CoinGeckoDataProvider(_HttpMarketDataProvider):
    def __init__(self) -> None:
        from app.services.market_data.http_providers import CoinGeckoClient

        super().__init__(
            name="coingecko",
            api_key_env="COINGECKO_API_KEY",
            client_factory=CoinGeckoClient,
            requires_api_key=False,  # public demo works; key optional
            priority=55,
            rpm=30,
            crypto_only=True,
        )
