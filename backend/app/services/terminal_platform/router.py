"""ProviderRouter — priority chains, fallback, rate limit, circuit breaker, cache."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import date, datetime
from typing import Any, Optional

from app.core.logging import get_logger
from app.services.terminal_platform.base import DataProvider
from app.services.terminal_platform.cache import TerminalCache
from app.services.terminal_platform.circuit_breaker import CircuitBreaker, CircuitState
from app.services.terminal_platform.models import FetchResult, ProviderHealth
from app.services.terminal_platform.providers._helpers import (
    SOFT_PROVIDER_ERROR_CODES,
    classify_provider_error,
)
from app.services.terminal_platform.rate_limiter import RateLimiter
from app.services.terminal_platform.types import (
    CircuitBreakerConfig,
    DataType,
    ProviderStatus,
    Timeframe,
)

logger = get_logger(__name__)

# Hard caps so OPEN/degraded/slow foreign providers cannot block Terminal ≤30s budget.
_PROVIDER_CALL_TIMEOUT_S = 2.5
_CHAIN_BUDGET_S = 5.0
_RATE_LIMIT_WAIT_S = 0.35

# Default fallback order by data capability. Providers not supporting the type are skipped.
# Crypto → binance_public / coingecko; equities → keyed HTTP chain before yfinance/AV.
# Yahoo indices often hang on RU VPS proxy — prefer FMP before yfinance when keyed.
DEFAULT_CHAINS: dict[DataType, list[str]] = {
    DataType.QUOTE: [
        "binance_public",
        "coingecko",
        "forex",
        "moex_iss",
        "alpaca",
        "polygon",
        "twelvedata",
        "tiingo",
        "marketstack",
        "finnhub",
        "fmp",
        "stooq",
        "yfinance",
        "alpha_vantage",
    ],
    DataType.OHLCV: [
        "binance_public",
        "coingecko",
        "forex",
        "moex_iss",
        "alpaca",
        "polygon",
        "twelvedata",
        "tiingo",
        "marketstack",
        "finnhub",
        "fmp",
        "stooq",
        "yfinance",
        "alpha_vantage",
    ],
    DataType.MACRO_SERIES: [
        "cbr",
        "fred",
        "eia",
        "ecb",
        "oecd",
        "eurostat",
        "imf",
        "world_bank",
        "rosstat",
    ],
    DataType.FUNDAMENTALS: ["moex_iss", "fmp", "yfinance", "alpha_vantage"],
    DataType.NEWS: [
        "finnhub",
        "polygon",
        "tiingo",
        "fmp",
        "alpha_vantage",
        "yfinance",
    ],
}

# Soft failures must not trip the circuit (skip provider, try next).
_SOFT_ERROR_CODES = SOFT_PROVIDER_ERROR_CODES

# US/global equity HTTP venues — Yahoo-style indices/futures are wrong symbols here.
_EQUITY_HTTP_PROVIDERS = frozenset(
    {"alpaca", "polygon", "twelvedata", "tiingo", "marketstack", "finnhub"}
)

_CRYPTO_SYMBOLS = frozenset(
    {
        "BTC",
        "BTCUSD",
        "BTCUSDT",
        "BTC-USD",
        "BTC/USDT",
        "ETH",
        "ETHUSD",
        "ETHUSDT",
        "ETH-USD",
        "ETH/USDT",
    }
)


class ProviderRouter:
    """
    Routes terminal data requests across registered providers.

    Features:
    - priority / fallback chains per DataType (overridable)
    - per-provider rate limiting
    - circuit breaker (skip tripped providers)
    - Redis + memory response cache
    """

    def __init__(
        self,
        providers: Optional[list[DataProvider]] = None,
        *,
        chains: Optional[dict[DataType, list[str]]] = None,
        cache: Optional[TerminalCache] = None,
        circuit_config: Optional[CircuitBreakerConfig] = None,
        cache_ttl_seconds: int = 120,
    ):
        self._providers: dict[str, DataProvider] = {}
        self._limiters: dict[str, RateLimiter] = {}
        self._breakers: dict[str, CircuitBreaker] = {}
        self.chains = chains or dict(DEFAULT_CHAINS)
        self.cache = cache or TerminalCache(default_ttl_seconds=cache_ttl_seconds)
        self.circuit_config = circuit_config or CircuitBreakerConfig()
        if providers:
            for p in providers:
                self.register(p)

    def register(self, provider: DataProvider) -> None:
        self._providers[provider.name] = provider
        self._limiters[provider.name] = RateLimiter(provider.config.rate_limit)
        self._breakers[provider.name] = CircuitBreaker(provider.name, self.circuit_config)

    def get_provider(self, name: str) -> Optional[DataProvider]:
        return self._providers.get(name)

    def list_providers(self) -> list[DataProvider]:
        return list(self._providers.values())

    def _chain_for(self, data_type: DataType, preferred: Optional[str] = None) -> list[DataProvider]:
        names = list(self.chains.get(data_type, []))
        if preferred and preferred in self._providers:
            names = [preferred] + [n for n in names if n != preferred]
        # Append any registered providers supporting the type that aren't listed.
        for name, provider in sorted(
            self._providers.items(),
            key=lambda kv: (-kv[1].config.priority, kv[0]),
        ):
            if name not in names and provider.supports(data_type):
                names.append(name)
        result: list[DataProvider] = []
        for name in names:
            provider = self._providers.get(name)
            if provider is None:
                continue
            if not provider.config.enabled:
                continue
            if not provider.supports(data_type):
                continue
            result.append(provider)
        return result

    @staticmethod
    def _cache_key(op: str, **params: Any) -> str:
        payload = json.dumps(params, sort_keys=True, default=str)
        digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
        return f"{op}:{digest}"

    async def _call_provider(
        self,
        provider: DataProvider,
        data_type: DataType,
        **kwargs: Any,
    ) -> FetchResult:
        breaker = self._breakers[provider.name]
        # Never wait on OPEN circuits — fail soft and let fallbacks run.
        if not breaker.allow_request():
            return FetchResult(
                success=False,
                error=f"Circuit open for {provider.name}",
                error_code="CIRCUIT_OPEN",
                provider=provider.name,
            )

        limiter = self._limiters[provider.name]
        if not await limiter.acquire(timeout=_RATE_LIMIT_WAIT_S):
            provider._update_status(ProviderStatus.RATE_LIMITED, "rate limited")
            # Soft — do not trip circuit; let fallbacks run.
            return FetchResult(
                success=False,
                error="Rate limited",
                error_code="RATE_LIMIT",
                provider=provider.name,
            )

        # Skip providers that cannot handle this symbol (e.g. binance for equities).
        symbol = kwargs.get("symbol")
        routed = None
        if isinstance(symbol, str) and data_type in (DataType.QUOTE, DataType.OHLCV):
            from app.services.instrument.asset_class import RoutingClass, classify_symbol

            routed = classify_symbol(symbol)
        if (
            data_type in (DataType.QUOTE, DataType.OHLCV)
            and provider.name.startswith("ccxt_")
            and routed is not None
            and routed.routing_class != RoutingClass.CRYPTO_PAIR
        ):
            return FetchResult(
                success=False,
                error=f"{provider.name}: non-crypto symbol",
                error_code="UNSUPPORTED",
                provider=provider.name,
            )
        if (
            data_type in (DataType.QUOTE, DataType.OHLCV)
            and provider.name == "binance_public"
            and routed is not None
            and routed.routing_class != RoutingClass.CRYPTO_PAIR
        ):
            return FetchResult(
                success=False,
                error="binance_public: equity/index/forex symbol",
                error_code="UNSUPPORTED",
                provider=provider.name,
            )
        if (
            data_type in (DataType.QUOTE, DataType.OHLCV)
            and provider.name == "forex"
            and routed is not None
            and routed.routing_class != RoutingClass.FOREX_PAIR
        ):
            return FetchResult(
                success=False,
                error="forex: not a classic OTC pair",
                error_code="UNSUPPORTED",
                provider=provider.name,
            )
        if (
            data_type in (DataType.QUOTE, DataType.OHLCV)
            and provider.name == "moex_iss"
            and routed is not None
        ):
            if routed.market not in {"moex", "moex_fx"}:
                return FetchResult(
                    success=False,
                    error="moex_iss: non-MOEX symbol",
                    error_code="UNSUPPORTED",
                    provider=provider.name,
                )
        if (
            data_type in (DataType.QUOTE, DataType.OHLCV)
            and provider.name in _EQUITY_HTTP_PROVIDERS
            and routed is not None
        ):
            # Alpaca/Polygon reject Yahoo indices and forex; Marketstack/Twelve Data
            # are allowed for international names.
            if routed.routing_class == RoutingClass.CRYPTO_PAIR:
                return FetchResult(
                    success=False,
                    error=f"{provider.name}: crypto symbol",
                    error_code="UNSUPPORTED",
                    provider=provider.name,
                )
            if routed.routing_class == RoutingClass.FOREX_PAIR and provider.name != "twelvedata":
                return FetchResult(
                    success=False,
                    error=f"{provider.name}: forex symbol",
                    error_code="UNSUPPORTED",
                    provider=provider.name,
                )
            sym_u = routed.canonical_symbol
            if provider.name in {"alpaca", "polygon"} and (
                routed.routing_class == RoutingClass.INTERNATIONAL
                or sym_u.startswith("^")
                or "=" in sym_u
                or routed.market in {"moex", "moex_fx"}
            ):
                return FetchResult(
                    success=False,
                    error=f"{provider.name}: unsupported index/intl/MOEX symbol",
                    error_code="UNSUPPORTED",
                    provider=provider.name,
                )
            if provider.name in {"tiingo", "finnhub"} and (
                routed.routing_class in {RoutingClass.INTERNATIONAL, RoutingClass.FOREX_PAIR}
                or sym_u.startswith("^")
                or "=" in sym_u
            ):
                return FetchResult(
                    success=False,
                    error=f"{provider.name}: unsupported index/intl symbol",
                    error_code="UNSUPPORTED",
                    provider=provider.name,
                )

        call_timeout = min(
            float(getattr(provider.config, "timeout_seconds", _PROVIDER_CALL_TIMEOUT_S) or _PROVIDER_CALL_TIMEOUT_S),
            _PROVIDER_CALL_TIMEOUT_S,
        )

        async def _invoke() -> FetchResult:
            if data_type == DataType.QUOTE:
                return await provider.fetch_quote(**kwargs)
            if data_type == DataType.OHLCV:
                return await provider.fetch_ohlcv(**kwargs)
            if data_type == DataType.MACRO_SERIES:
                return await provider.fetch_macro_series(**kwargs)
            if data_type == DataType.FUNDAMENTALS:
                return await provider.fetch_fundamentals(**kwargs)
            if data_type == DataType.NEWS:
                return await provider.fetch_news(**kwargs)
            return FetchResult(
                success=False,
                error=f"Unsupported data type {data_type}",
                error_code="UNSUPPORTED",
                provider=provider.name,
            )

        try:
            result = await asyncio.wait_for(_invoke(), timeout=call_timeout)
        except asyncio.TimeoutError:
            msg = f"provider timeout after {call_timeout:.1f}s"
            logger.warning(
                "terminal provider timeout",
                provider=provider.name,
                data_type=data_type.value,
                timeout_s=call_timeout,
            )
            # Soft — do not trip circuit on proxy timeouts (fallbacks cover).
            return FetchResult(
                success=False,
                error=msg,
                error_code="TIMEOUT",
                provider=provider.name,
            )
        except Exception as exc:
            from app.utils.secret_redact import redact_secrets

            safe = redact_secrets(str(exc)) or str(exc)
            code = classify_provider_error(exc)
            logger.warning(
                "terminal provider raised",
                provider=provider.name,
                data_type=data_type.value,
                error=safe,
                error_code=code,
            )
            if code not in _SOFT_ERROR_CODES:
                breaker.record_failure()
                provider._update_status(ProviderStatus.DEGRADED, safe)
            return FetchResult(
                success=False,
                error=safe,
                error_code=code,
                provider=provider.name,
            )

        if result.success:
            breaker.record_success()
            if provider.status != ProviderStatus.ACTIVE:
                provider._update_status(ProviderStatus.ACTIVE)
        else:
            # Soft failures (key missing, rate limit, unsupported) — don't trip circuit.
            code = result.error_code or classify_provider_error(result.error or "")
            if code not in _SOFT_ERROR_CODES:
                breaker.record_failure()
            if breaker.state == CircuitState.OPEN:
                provider._update_status(ProviderStatus.CIRCUIT_OPEN, result.error)
        return result

    async def fetch(
        self,
        data_type: DataType,
        *,
        preferred_provider: Optional[str] = None,
        use_cache: bool = True,
        cache_ttl: Optional[int] = None,
        chain_budget_s: Optional[float] = None,
        **kwargs: Any,
    ) -> FetchResult:
        cache_key = self._cache_key(data_type.value, **kwargs)
        if use_cache:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                try:
                    result = FetchResult.model_validate(cached)
                    result.from_cache = True
                    return result
                except Exception:
                    pass

        symbol = kwargs.get("symbol")
        if preferred_provider is None and isinstance(symbol, str):
            from app.services.market_data.marketstack_catalog import is_marketstack_catalog_symbol

            if is_marketstack_catalog_symbol(symbol):
                preferred_provider = "marketstack"

        errors: list[str] = []
        chain = self._chain_for(data_type, preferred_provider)
        if not chain:
            return FetchResult(
                success=False,
                error=f"No providers registered for {data_type.value}",
                error_code="NO_PROVIDERS",
                provider="router",
            )

        budget = float(chain_budget_s) if chain_budget_s is not None else _CHAIN_BUDGET_S
        deadline = time.monotonic() + max(0.5, budget)

        for provider in chain:
            if time.monotonic() >= deadline:
                errors.append("chain_budget_exhausted")
                break
            # Skip OPEN circuits without spending budget (allow_request may half-open).
            breaker = self._breakers.get(provider.name)
            if breaker is not None and breaker.state == CircuitState.OPEN:
                if not breaker.allow_request():
                    errors.append(f"{provider.name}:CIRCUIT_OPEN")
                    continue
            result = await self._call_provider(provider, data_type, **kwargs)
            if result.success:
                if use_cache:
                    await self.cache.set(
                        cache_key,
                        result.model_dump(mode="json"),
                        ttl=cache_ttl,
                    )
                result.metadata = {
                    **(result.metadata or {}),
                    "fallback_tried": errors,
                    "selected_provider": provider.name,
                }
                return result
            errors.append(f"{provider.name}:{result.error_code or result.error}")

        return FetchResult(
            success=False,
            error="All providers failed: " + "; ".join(errors),
            error_code="ALL_FAILED",
            provider="router",
            metadata={"attempts": errors},
        )

    async def get_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        return await self.fetch(DataType.QUOTE, symbol=symbol, **kwargs)

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: datetime,
        to_date: datetime,
        **kwargs: Any,
    ) -> FetchResult:
        return await self.fetch(
            DataType.OHLCV,
            symbol=symbol,
            timeframe=timeframe,
            from_date=from_date,
            to_date=to_date,
            **kwargs,
        )

    async def get_macro(
        self,
        series_id: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        **kwargs: Any,
    ) -> FetchResult:
        return await self.fetch(
            DataType.MACRO_SERIES,
            series_id=series_id,
            from_date=from_date,
            to_date=to_date,
            **kwargs,
        )

    async def get_news(
        self,
        symbols: Optional[list[str]] = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> FetchResult:
        return await self.fetch(DataType.NEWS, symbols=symbols, limit=limit, **kwargs)

    def reset_all_circuits(self) -> dict[str, str]:
        """Force-close every circuit (ops recovery after rate-limit storms)."""
        out: dict[str, str] = {}
        for name, breaker in self._breakers.items():
            prev = breaker.state.value
            breaker.reset()
            provider = self._providers.get(name)
            if provider is not None and provider.status in (
                ProviderStatus.CIRCUIT_OPEN,
                ProviderStatus.DEGRADED,
                ProviderStatus.RATE_LIMITED,
            ):
                provider._update_status(ProviderStatus.ACTIVE)
            out[name] = f"{prev}->closed"
        return out

    def reset_open_circuits(self, *, min_open_seconds: float = 0.0) -> dict[str, str]:
        """
        Reset circuits that are OPEN (or HALF_OPEN) after min_open_seconds.
        Enables faster recovery than waiting full recovery_timeout alone.
        """
        import time as _time

        out: dict[str, str] = {}
        now = _time.monotonic()
        for name, breaker in self._breakers.items():
            if breaker.state == CircuitState.CLOSED:
                continue
            opened = breaker.opened_at
            age = (now - opened) if opened is not None else min_open_seconds
            if age < min_open_seconds:
                continue
            prev = breaker.state.value
            breaker.reset()
            provider = self._providers.get(name)
            if provider is not None and provider.status in (
                ProviderStatus.CIRCUIT_OPEN,
                ProviderStatus.DEGRADED,
                ProviderStatus.RATE_LIMITED,
            ):
                provider._update_status(ProviderStatus.ACTIVE)
            out[name] = f"{prev}->closed"
        return out

    async def providers_health(self) -> list[ProviderHealth]:
        # Opportunistic half-open: allow recovery probe after cooldown without waiting for next call.
        for breaker in self._breakers.values():
            breaker.allow_request()  # may transition OPEN → HALF_OPEN

        out: list[ProviderHealth] = []
        for provider in self.list_providers():
            breaker = self._breakers[provider.name]
            # Refresh credentials before reporting — avoids stale "key missing" after .env update.
            keyed = provider.api_key_configured
            available = await provider.health_check() and breaker.state != CircuitState.OPEN
            status_val = provider.status.value
            # Key present but still UNAVAILABLE only due to prior missing-key soft-fail → treat active.
            if keyed and status_val == "unavailable" and provider._last_error and "Missing API key" in provider._last_error:
                status_val = "active"
                available = breaker.state != CircuitState.OPEN
            # Circuit already recovered → clear stale CIRCUIT_OPEN status label.
            if status_val == "circuit_open" and breaker.state == CircuitState.CLOSED:
                status_val = "active"
                available = True
            from app.utils.secret_redact import redact_secrets

            last_err = None if (keyed and status_val == "active") else redact_secrets(provider._last_error)
            out.append(
                ProviderHealth(
                    name=provider.name,
                    status=status_val,
                    available=available,
                    last_error=last_err,
                    circuit_state=breaker.state.value,
                    supported_data_types=[dt.value for dt in provider.supported_data_types],
                    requires_api_key=provider.config.requires_api_key,
                    api_key_configured=keyed,
                )
            )
        return out
