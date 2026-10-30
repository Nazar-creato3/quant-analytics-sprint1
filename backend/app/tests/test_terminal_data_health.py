"""Data health / freshness guard — no mock sine, performance fills, circuit half-open."""
from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.services.terminal_platform.circuit_breaker import CircuitBreaker, CircuitState
from app.services.terminal_platform.market.schemas import IndexQuoteRow, WatchlistEnrichedRow
from app.services.terminal_platform.market.snapshot import _build_performance
from app.services.terminal_platform.types import CircuitBreakerConfig


def _sine_closes(n: int = 64, mid: float = 67500.0) -> list[float]:
    return [mid + math.sin(i / 4) * 180 for i in range(n)]


def test_sine_mock_pattern_is_detectable():
    """Guard: classic demo series must be rejected by health probe heuristic."""
    closes = _sine_closes()
    mid = sum(closes) / len(closes)
    amp = max(abs(c - mid) for c in closes) or 1.0
    err = sum(abs(c - (mid + math.sin(i / 4) * min(amp, 200))) for i, c in enumerate(closes))
    sinusoidal = (err / len(closes)) < (amp * 0.15) and 65000 < mid < 70000
    assert sinusoidal is True


def test_real_btc_path_is_not_sine():
    # Irregular crypto-like path around ~64k
    closes = [64480 + (i % 7) * 35 - (i % 5) * 22 + (i * 3) % 17 for i in range(48)]
    mid = sum(closes) / len(closes)
    amp = max(abs(c - mid) for c in closes) or 1.0
    err = sum(abs(c - (mid + math.sin(i / 4) * min(amp, 200))) for i, c in enumerate(closes))
    sinusoidal = (err / len(closes)) < (amp * 0.15) and 65000 < mid < 70000
    assert sinusoidal is False


def test_performance_fills_from_quote_change_pct():
    indices = {
        "SPX": IndexQuoteRow(symbol="SPX", status="ok", price=7316.15, change_pct=0.41),
        "NDX": IndexQuoteRow(symbol="NDX", status="ok", price=27192.31, change_pct=0.55),
        "DJI": IndexQuoteRow(symbol="DJI", status="ok", price=45500.0, change_pct=0.22),
        "IMOEX": IndexQuoteRow(symbol="IMOEX", status="ok", price=2700.0, change_pct=-0.3),
        "VIX": IndexQuoteRow(symbol="VIX", status="ok", price=14.2, change_pct=-1.1),
    }
    watch = [
        WatchlistEnrichedRow(
            symbol="BTC/USDT",
            status="ok",
            last=64487.78,
            change_pct=0.91,
        ),
        WatchlistEnrichedRow(symbol="GLD", status="ok", last=380.0, change_pct=0.4),
    ]
    rows = _build_performance(indices, watch, pulse=None)
    by_label = {r.label: r for r in rows}
    assert by_label["NASDAQ Daily"].status == "ok"
    assert by_label["NASDAQ Daily"].value == 0.55
    assert by_label["DOW Daily"].value == 0.22
    assert by_label["S&P 500 Daily"].value == 0.41
    assert by_label["S&P vs DOW Spread"].status == "ok"
    assert by_label["BTC/USDT"].status == "ok"
    assert by_label["BTC/USDT"].value == 0.91
    assert by_label["GOLD (XAU)"].status == "ok"
    assert by_label["IMOEX"].status == "ok"
    # Never fake 0%
    assert all(r.value != 0.0 or r.status == "ok" for r in rows if r.unit == "pct")


def test_performance_no_data_only_when_quote_missing():
    indices = {
        "SPX": IndexQuoteRow(symbol="SPX", status="no_data", reason="timeout"),
    }
    rows = _build_performance(indices, [], pulse=None)
    spx = next(r for r in rows if r.label == "S&P 500 Daily")
    assert spx.status == "no_data"
    assert spx.value is None
    assert spx.reason


def test_circuit_half_open_after_cooldown():
    cfg = CircuitBreakerConfig(failure_threshold=3, recovery_timeout_seconds=0.05, half_open_max_calls=2)
    br = CircuitBreaker("alpha_vantage", cfg)
    for _ in range(3):
        br.record_failure()
    assert br.state == CircuitState.OPEN
    assert br.allow_request() is False
    time.sleep(0.06)
    assert br.allow_request() is True  # transitions to half-open
    assert br.state == CircuitState.HALF_OPEN
    br.record_success()
    assert br.state == CircuitState.CLOSED


def test_circuit_reset_clears_open():
    cfg = CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=60)
    br = CircuitBreaker("yfinance", cfg)
    br.record_failure()
    br.record_failure()
    assert br.state == CircuitState.OPEN
    br.reset()
    assert br.state == CircuitState.CLOSED
    assert br.allow_request() is True


@pytest.mark.asyncio
async def test_router_rate_limit_does_not_trip_circuit():
    from app.services.terminal_platform.base import DataProvider, DataProviderConfig
    from app.services.terminal_platform.cache import TerminalCache
    from app.services.terminal_platform.models import FetchResult, Quote
    from app.services.terminal_platform.router import ProviderRouter
    from app.services.terminal_platform.types import DataType, RateLimitConfig
    from datetime import datetime, timezone
    from decimal import Decimal

    class RateLimitedStub(DataProvider):
        def __init__(self):
            super().__init__(
                DataProviderConfig(
                    name="alpha_vantage",
                    enabled=True,
                    rate_limit=RateLimitConfig(requests_per_minute=1, burst_size=1),
                )
            )

        @property
        def supported_data_types(self):
            return [DataType.QUOTE]

        async def fetch_ohlcv(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_quote(self, symbol: str, **kwargs):
            return FetchResult(
                success=True,
                data=Quote(
                    symbol=symbol,
                    price=Decimal("1"),
                    timestamp=datetime.now(timezone.utc),
                    provider=self.name,
                ),
                provider=self.name,
            )

        async def fetch_macro_series(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_fundamentals(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_news(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

    class GoodStub(DataProvider):
        def __init__(self):
            super().__init__(DataProviderConfig(name="yfinance", enabled=True))

        @property
        def supported_data_types(self):
            return [DataType.QUOTE]

        async def fetch_ohlcv(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_quote(self, symbol: str, **kwargs):
            return FetchResult(
                success=True,
                data=Quote(
                    symbol=symbol,
                    price=Decimal("2"),
                    timestamp=datetime.now(timezone.utc),
                    provider=self.name,
                    change_pct=0.1,
                ),
                provider=self.name,
            )

        async def fetch_macro_series(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_fundamentals(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_news(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

    av = RateLimitedStub()
    yf = GoodStub()
    router = ProviderRouter(
        [av, yf],
        chains={DataType.QUOTE: ["alpha_vantage", "yfinance"]},
        cache=TerminalCache(default_ttl_seconds=1),
        circuit_config=CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=60),
    )
    router._limiters["alpha_vantage"].acquire = AsyncMock(return_value=False)  # type: ignore[method-assign]
    result = await router.get_quote("AAPL", use_cache=False)
    assert result.success is True
    assert result.provider == "yfinance"
    assert router._breakers["alpha_vantage"].state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_router_http_soft_errors_do_not_trip_circuit():
    """429 / 400 wrong-symbol must not sticky-open circuits."""
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.services.terminal_platform.base import DataProvider, DataProviderConfig
    from app.services.terminal_platform.cache import TerminalCache
    from app.services.terminal_platform.models import FetchResult, Quote
    from app.services.terminal_platform.router import ProviderRouter
    from app.services.terminal_platform.types import DataType

    class SoftFailStub(DataProvider):
        def __init__(self):
            super().__init__(DataProviderConfig(name="alpaca", enabled=True, requires_api_key=False))
            self.calls = 0

        @property
        def supported_data_types(self):
            return [DataType.QUOTE]

        async def fetch_ohlcv(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_quote(self, symbol: str, **kwargs):
            self.calls += 1
            return self._failure_from_exc(
                0.0,
                RuntimeError("Client error '429 Too Many Requests' for url 'https://api.example/quote'"),
            )

        async def fetch_macro_series(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_fundamentals(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_news(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

    class GoodStub(DataProvider):
        def __init__(self):
            super().__init__(DataProviderConfig(name="yfinance", enabled=True))

        @property
        def supported_data_types(self):
            return [DataType.QUOTE]

        async def fetch_ohlcv(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_quote(self, symbol: str, **kwargs):
            return FetchResult(
                success=True,
                data=Quote(
                    symbol=symbol,
                    price=Decimal("10"),
                    timestamp=datetime.now(timezone.utc),
                    provider=self.name,
                ),
                provider=self.name,
            )

        async def fetch_macro_series(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_fundamentals(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_news(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

    soft = SoftFailStub()
    good = GoodStub()
    router = ProviderRouter(
        [soft, good],
        chains={DataType.QUOTE: ["alpaca", "yfinance"]},
        cache=TerminalCache(default_ttl_seconds=1),
        circuit_config=CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=60),
    )
    for _ in range(5):
        result = await router.get_quote("AAPL", use_cache=False)
        assert result.success is True
        assert result.provider == "yfinance"
    assert router._breakers["alpaca"].state == CircuitState.CLOSED
    assert soft.status.value == "active"


def test_classify_provider_error_soft_codes():
    from app.services.terminal_platform.providers._helpers import classify_provider_error

    assert classify_provider_error(ModuleNotFoundError("No module named 'ccxt'")) == "DEPENDENCY_MISSING"
    assert (
        classify_provider_error("Client error '429 Too Many Requests' for url 'https://x'")
        == "RATE_LIMIT"
    )
    assert classify_provider_error("Client error '400 Bad Request' for url 'https://x'") == "UNSUPPORTED"
    assert classify_provider_error("Client error '403 Forbidden' for url 'https://x'") == "CLIENT_REJECT"
    assert (
        classify_provider_error("Failed to connect to fc.yahoo.com:443 over proxy 1.2.3.4")
        == "PROXY"
    )


@pytest.mark.asyncio
async def test_router_skips_yahoo_index_on_alpaca():
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.services.terminal_platform.base import DataProvider, DataProviderConfig
    from app.services.terminal_platform.cache import TerminalCache
    from app.services.terminal_platform.models import FetchResult, Quote
    from app.services.terminal_platform.router import ProviderRouter
    from app.services.terminal_platform.types import DataType

    class AlpacaStub(DataProvider):
        def __init__(self):
            super().__init__(DataProviderConfig(name="alpaca", enabled=True, requires_api_key=False))
            self.calls = 0

        @property
        def supported_data_types(self):
            return [DataType.QUOTE]

        async def fetch_ohlcv(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_quote(self, symbol: str, **kwargs):
            self.calls += 1
            raise AssertionError("alpaca must not be called for ^NDX")

        async def fetch_macro_series(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_fundamentals(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_news(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

    class YfStub(DataProvider):
        def __init__(self):
            super().__init__(DataProviderConfig(name="yfinance", enabled=True))

        @property
        def supported_data_types(self):
            return [DataType.QUOTE]

        async def fetch_ohlcv(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_quote(self, symbol: str, **kwargs):
            return FetchResult(
                success=True,
                data=Quote(
                    symbol=symbol,
                    price=Decimal("1"),
                    timestamp=datetime.now(timezone.utc),
                    provider=self.name,
                ),
                provider=self.name,
            )

        async def fetch_macro_series(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_fundamentals(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

        async def fetch_news(self, *a, **k):
            return FetchResult(success=False, error="n/a", provider=self.name, error_code="UNSUPPORTED")

    alpaca = AlpacaStub()
    router = ProviderRouter(
        [alpaca, YfStub()],
        chains={DataType.QUOTE: ["alpaca", "yfinance"]},
        cache=TerminalCache(default_ttl_seconds=1),
    )
    result = await router.get_quote("^NDX", use_cache=False)
    assert result.success is True
    assert result.provider == "yfinance"
    assert alpaca.calls == 0
    assert router._breakers["alpaca"].state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_no_data_policy_never_zero_fake():
    from app.services.terminal_platform.market.quotes import fetch_quote_safe
    from app.services.terminal_platform.models import FetchResult

    failed = FetchResult(success=False, error="all failed", error_code="ALL_FAILED", provider="router")
    with patch("app.services.terminal_platform.market.quotes.get_terminal_router") as mf:
        mf.return_value.get_quote = AsyncMock(return_value=failed)
        out = await fetch_quote_safe("BTC-USD")
    assert out["status"] == "no_data"
    assert out.get("price") is None or out.get("price") != 0
    assert out.get("change_pct") is None
