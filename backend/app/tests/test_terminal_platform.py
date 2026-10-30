"""Tests for terminal platform Data Connector Architecture."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest

from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.cache import TerminalCache
from app.services.terminal_platform.circuit_breaker import CircuitBreaker, CircuitState
from app.services.terminal_platform.models import (
    FetchResult,
    Fundamentals,
    MacroSeries,
    NewsItem,
    OHLCV,
    Quote,
)
from app.services.terminal_platform.router import ProviderRouter
from app.services.terminal_platform.types import (
    CircuitBreakerConfig,
    DataType,
    Timeframe,
)


class _StubProvider(DataProvider):
    """Test double that records calls and returns scripted results."""

    def __init__(
        self,
        name: str,
        *,
        types: list[DataType] | None = None,
        quote_result: FetchResult | None = None,
        fail_times: int = 0,
        priority: int = 0,
    ):
        super().__init__(
            DataProviderConfig(name=name, priority=priority, enabled=True)
        )
        self._types = types or [DataType.QUOTE]
        self._quote_result = quote_result
        self._fail_times = fail_times
        self._calls = 0

    @property
    def supported_data_types(self) -> list[DataType]:
        return self._types

    async def fetch_ohlcv(self, symbol, timeframe, from_date, to_date, **kwargs):
        return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        self._calls += 1
        if self._calls <= self._fail_times:
            return FetchResult(
                success=False,
                error="forced failure",
                error_code="FORCED",
                provider=self.name,
            )
        if self._quote_result:
            return self._quote_result
        return FetchResult(
            success=True,
            data=Quote(
                symbol=symbol,
                price=Decimal("100"),
                timestamp=datetime.now(timezone.utc),
                provider=self.name,
            ),
            provider=self.name,
        )

    async def fetch_macro_series(self, series_id, from_date=None, to_date=None, **kwargs):
        return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

    async def fetch_fundamentals(self, symbol, **kwargs):
        return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

    async def fetch_news(self, symbols=None, from_date=None, to_date=None, limit=50, **kwargs):
        return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")


@pytest.mark.asyncio
async def test_router_fallback_uses_second_provider():
    primary = _StubProvider("primary", fail_times=1, priority=10)
    fallback = _StubProvider(
        "fallback",
        quote_result=FetchResult(
            success=True,
            data=Quote(
                symbol="AAPL",
                price=Decimal("150"),
                timestamp=datetime.now(timezone.utc),
                provider="fallback",
            ),
            provider="fallback",
        ),
        priority=1,
    )
    router = ProviderRouter(
        [primary, fallback],
        chains={DataType.QUOTE: ["primary", "fallback"]},
        cache=TerminalCache(default_ttl_seconds=1),
    )
    # Disable cache for this call to avoid cross-test pollution
    result = await router.get_quote("AAPL", use_cache=False)
    assert result.success is True
    assert result.provider == "fallback"
    assert primary._calls == 1
    assert fallback._calls == 1


@pytest.mark.asyncio
async def test_circuit_breaker_skips_open_provider():
    breaker_cfg = CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=60)
    bad = _StubProvider("bad", fail_times=99, priority=10)
    good = _StubProvider(
        "good",
        quote_result=FetchResult(
            success=True,
            data=Quote(
                symbol="MSFT",
                price=Decimal("300"),
                timestamp=datetime.now(timezone.utc),
                provider="good",
            ),
            provider="good",
        ),
    )
    router = ProviderRouter(
        [bad, good],
        chains={DataType.QUOTE: ["bad", "good"]},
        circuit_config=breaker_cfg,
        cache=TerminalCache(default_ttl_seconds=1),
    )

    # Trip the circuit on "bad"
    await router.get_quote("MSFT", use_cache=False)
    await router.get_quote("MSFT", use_cache=False)
    assert router._breakers["bad"].state == CircuitState.OPEN

    calls_before = bad._calls
    result = await router.get_quote("MSFT", use_cache=False)
    assert result.success is True
    assert result.provider == "good"
    # Circuit open → no additional call to bad
    assert bad._calls == calls_before


def test_circuit_breaker_unit_trip_and_half_open():
    cb = CircuitBreaker(
        "x",
        CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=0.01),
    )
    assert cb.allow_request() is True
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    # After cool-down, next allow transitions to half-open.
    import time as _time

    _time.sleep(0.02)
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_model_validation_ohlcv_quote_macro_fundamentals_news():
    bar = OHLCV(
        symbol="SBER",
        timeframe="1d",
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        open=Decimal("250.1"),
        high=Decimal("255"),
        low=Decimal("249"),
        close=Decimal("253.5"),
        volume=Decimal("1000000"),
        provider="moex_iss",
        currency="RUB",
        exchange="MOEX",
    )
    assert bar.close == Decimal("253.5")

    quote = Quote(
        symbol="AAPL",
        price=Decimal("190.5"),
        timestamp=datetime.now(timezone.utc),
        provider="yfinance",
    )
    assert quote.price > 0

    macro = MacroSeries(
        series_id="FEDFUNDS",
        name="Fed Funds",
        values=[{"date": "2024-01-01", "value": 5.33}],
        provider="fred",
        country="US",
        unit="percent",
    )
    assert macro.values[0]["value"] == 5.33

    fund = Fundamentals(
        symbol="AAPL",
        company_name="Apple Inc",
        pe_ratio=Decimal("28.5"),
        provider="fmp",
    )
    assert fund.company_name.startswith("Apple")

    news = NewsItem(
        title="Test headline",
        source="unit-test",
        url="https://example.com/a",
        published_at=datetime.now(timezone.utc),
        provider="alpha_vantage",
    )
    assert news.title

    with pytest.raises(Exception):
        OHLCV(
            symbol="X",
            timeframe="1d",
            timestamp=datetime.now(timezone.utc),
            open="not-a-decimal",  # type: ignore[arg-type]
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            provider="x",
        )


@pytest.mark.asyncio
async def test_key_missing_provider_degrades_without_breaking_router():
    from app.services.terminal_platform.providers.fred import FredDataProvider

    fred = FredDataProvider()
    # Force missing key regardless of environment
    fred._api_key = None
    fred.config.requires_api_key = True

    good = _StubProvider(
        "cbr_stub",
        types=[DataType.MACRO_SERIES],
    )

    async def _macro(*args, **kwargs):
        from app.services.terminal_platform.models import MacroSeries

        return FetchResult(
            success=True,
            data=MacroSeries(
                series_id="KEY_RATE",
                name="CBR",
                values=[{"date": "2024-01-01", "value": 16.0}],
                provider="cbr_stub",
            ),
            provider="cbr_stub",
        )

    good.fetch_macro_series = _macro  # type: ignore[method-assign]

    router = ProviderRouter(
        [fred, good],
        chains={DataType.MACRO_SERIES: ["fred", "cbr_stub"]},
        cache=TerminalCache(default_ttl_seconds=1),
    )
    result = await router.get_macro("KEY_RATE", use_cache=False)
    assert result.success is True
    assert result.provider == "cbr_stub"


@pytest.mark.asyncio
async def test_memory_cache_hit():
    provider = _StubProvider("only")
    cache = TerminalCache(default_ttl_seconds=60)
    router = ProviderRouter(
        [provider],
        chains={DataType.QUOTE: ["only"]},
        cache=cache,
    )
    first = await router.get_quote("AAA", use_cache=True)
    second = await router.get_quote("AAA", use_cache=True)
    assert first.success and second.success
    assert second.from_cache is True
    assert provider._calls == 1
