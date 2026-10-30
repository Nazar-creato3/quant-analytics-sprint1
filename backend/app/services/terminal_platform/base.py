"""Abstract DataProvider base class (TET-style transform / extract / normalize)."""
from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.services.terminal_platform.models import (
    FetchResult,
    Fundamentals,
    MacroSeries,
    NewsItem,
    OHLCV,
    Quote,
)
from app.services.terminal_platform.types import (
    DataType,
    ProviderStatus,
    RateLimitConfig,
    RetryConfig,
    Timeframe,
)


class DataProviderConfig(BaseModel):
    """Base configuration for a concrete provider."""

    name: str
    enabled: bool = True
    api_key_env: Optional[str] = None
    api_secret_env: Optional[str] = None
    base_url: Optional[str] = None
    # Soft-fail fast — Terminal snapshot has a ≤30s hard budget; never hang on proxy.
    timeout_seconds: float = 3.0
    retry: RetryConfig = Field(default_factory=RetryConfig)
    rate_limit: Optional[RateLimitConfig] = None
    priority: int = Field(default=0, description="Higher = preferred within a chain")
    fallback_providers: list[str] = Field(default_factory=list)
    requires_api_key: bool = False


class DataProvider(ABC):
    """
    Abstract market/macro/news data provider.

    Subclasses implement fetch_* methods. Shared helpers handle credentials,
    timing, and status bookkeeping. ProviderRouter owns fallback / circuit breaker.
    """

    def __init__(self, config: DataProviderConfig):
        self.config = config
        self._status = ProviderStatus.ACTIVE if config.enabled else ProviderStatus.UNAVAILABLE
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[datetime] = None
        self._request_count = 0
        self._api_key: Optional[str] = None
        self._api_secret: Optional[str] = None
        self._initialize_credentials()

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def supported_data_types(self) -> list[DataType]:
        return []

    @property
    def supported_symbols(self) -> Optional[list[str]]:
        return None

    @property
    def api_key_configured(self) -> bool:
        if not self.config.requires_api_key and not self.config.api_key_env:
            return True
        if self._api_key:
            return True
        # Lazy re-read: provider may have been constructed before env/settings were ready.
        self._reload_api_key_from_env()
        return bool(self._api_key)

    def _reload_api_key_from_env(self) -> None:
        """Refresh API key from process env / settings without hardcoding secrets."""
        if not self.config.api_key_env:
            return
        env_val = (os.getenv(self.config.api_key_env) or "").strip() or None
        if env_val:
            self._api_key = env_val
        else:
            try:
                from app.core.config import get_settings

                value = getattr(get_settings(), self.config.api_key_env, None)
                if isinstance(value, str) and value.strip():
                    self._api_key = value.strip()
            except Exception:
                pass
        if self._api_key and self._status == ProviderStatus.UNAVAILABLE:
            # Key appeared after init — clear the "missing key" soft-fail.
            if self._last_error and "Missing API key" in self._last_error:
                self._status = ProviderStatus.ACTIVE
                self._last_error = None

    def _initialize_credentials(self) -> None:
        if self.config.api_key_env:
            self._api_key = (os.getenv(self.config.api_key_env) or "").strip() or None
        if self.config.api_secret_env:
            self._api_secret = (os.getenv(self.config.api_secret_env) or "").strip() or None
        # Prefer settings when env is empty (same keys, no hardcoding).
        if not self._api_key and self.config.api_key_env:
            try:
                from app.core.config import get_settings

                settings = get_settings()
                attr = self.config.api_key_env
                value = getattr(settings, attr, None)
                if isinstance(value, str) and value.strip():
                    self._api_key = value.strip()
            except Exception:
                pass
        if self.config.requires_api_key and not self._api_key:
            self._status = ProviderStatus.UNAVAILABLE
            self._last_error = f"Missing API key ({self.config.api_key_env})"

    def _record_request(self) -> None:
        self._request_count += 1

    def _update_status(self, status: ProviderStatus, error: Optional[str] = None) -> None:
        self._status = status
        if error:
            from app.utils.secret_redact import redact_secrets

            self._last_error = redact_secrets(error)
            self._last_error_time = datetime.now(timezone.utc)

    def _timed_failure(
        self,
        *,
        start: float,
        error: str,
        error_code: str = "PROVIDER_ERROR",
        status: Optional[ProviderStatus] = None,
    ) -> FetchResult:
        from app.services.terminal_platform.providers._helpers import SOFT_PROVIDER_ERROR_CODES
        from app.utils.secret_redact import redact_secrets

        safe_error = redact_secrets(error) or error
        # Soft skips (wrong symbol / empty / rate limit / proxy timeout) must NOT
        # sticky-mark the provider degraded — false "12 providers degraded" spam.
        soft_no_degrade = SOFT_PROVIDER_ERROR_CODES
        if status is None:
            if error_code == "KEY_MISSING":
                status = ProviderStatus.UNAVAILABLE
            elif error_code == "DEPENDENCY_MISSING":
                status = ProviderStatus.UNAVAILABLE
            elif error_code in soft_no_degrade:
                status = self._status
            else:
                status = ProviderStatus.DEGRADED
        if error_code in soft_no_degrade and status == self._status:
            # Expected skip — leave status/last_error alone.
            pass
        elif error_code == "DEPENDENCY_MISSING":
            # Missing optional dep (e.g. ccxt) — mark unavailable once, no sticky degrade.
            self._update_status(ProviderStatus.UNAVAILABLE, safe_error)
        else:
            self._update_status(status, safe_error)
        return FetchResult(
            success=False,
            error=safe_error,
            error_code=error_code,
            provider=self.name,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

    def _failure_from_exc(self, start: float, exc: BaseException) -> FetchResult:
        from app.services.terminal_platform.providers._helpers import classify_provider_error

        return self._timed_failure(
            start=start,
            error=str(exc),
            error_code=classify_provider_error(exc),
        )

    def _key_missing_result(self, start: float) -> FetchResult:
        msg = f"API key not configured ({self.config.api_key_env})"
        return self._timed_failure(
            start=start,
            error=msg,
            error_code="KEY_MISSING",
            status=ProviderStatus.UNAVAILABLE,
        )

    def _unsupported(self, start: float, data_type: str) -> FetchResult:
        return self._timed_failure(
            start=start,
            error=f"{self.name} does not support {data_type}",
            error_code="UNSUPPORTED",
            status=self._status,
        )

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: datetime,
        to_date: datetime,
        **kwargs: Any,
    ) -> FetchResult:
        ...

    @abstractmethod
    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        ...

    @abstractmethod
    async def fetch_macro_series(
        self,
        series_id: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        **kwargs: Any,
    ) -> FetchResult:
        ...

    @abstractmethod
    async def fetch_fundamentals(self, symbol: str, **kwargs: Any) -> FetchResult:
        ...

    @abstractmethod
    async def fetch_news(
        self,
        symbols: Optional[list[str]] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        **kwargs: Any,
    ) -> FetchResult:
        ...

    async def health_check(self) -> bool:
        if not self.config.enabled:
            return False
        # Always lazy-refresh before judging key presence / soft UNAVAILABLE.
        if self.config.requires_api_key or self.config.api_key_env:
            self._reload_api_key_from_env()
        if self.config.requires_api_key and not self._api_key:
            return False
        return self._status not in (ProviderStatus.UNAVAILABLE, ProviderStatus.CIRCUIT_OPEN)

    async def get_supported_symbols(self) -> list[str]:
        return list(self.supported_symbols or [])

    def supports(self, data_type: DataType) -> bool:
        return data_type in self.supported_data_types

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, status={self.status!r})"


# Re-export model types for provider modules.
__all__ = [
    "DataProvider",
    "DataProviderConfig",
    "FetchResult",
    "Fundamentals",
    "MacroSeries",
    "NewsItem",
    "OHLCV",
    "Quote",
]
