"""Shared enums and config models for terminal data connectors."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DataType(str, Enum):
    """Types of data the terminal platform can fetch."""

    OHLCV = "ohlcv"
    QUOTE = "quote"
    TRADE = "trade"
    ORDERBOOK = "orderbook"
    MACRO_SERIES = "macro_series"
    FUNDAMENTALS = "fundamentals"
    NEWS = "news"
    CORPORATE_ACTION = "corporate_action"


class Timeframe(str, Enum):
    """Supported bar intervals."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
    MN = "1mo"


class ProviderStatus(str, Enum):
    """Operational status of a data provider."""

    ACTIVE = "active"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"


class RetryConfig(BaseModel):
    """Retry policy for provider HTTP calls."""

    max_retries: int = Field(default=2, ge=0)
    base_delay_seconds: float = Field(default=0.5, gt=0)
    max_delay_seconds: float = Field(default=30.0, gt=0)
    exponential_base: float = Field(default=2.0, gt=1)
    jitter: bool = Field(default=True)


class RateLimitConfig(BaseModel):
    """Token-bucket style rate limit knobs."""

    requests_per_second: Optional[float] = Field(default=None, gt=0)
    requests_per_minute: Optional[int] = Field(default=None, gt=0)
    requests_per_day: Optional[int] = Field(default=None, gt=0)
    burst_size: int = Field(default=5, ge=1)


class CircuitBreakerConfig(BaseModel):
    """Trip after consecutive failures; cool down before half-open probe."""

    failure_threshold: int = Field(default=5, ge=1)
    # Keep cool-down short so proxy / rate-limit storms do not sticky-block Terminal.
    recovery_timeout_seconds: float = Field(default=60.0, gt=0)
    half_open_max_calls: int = Field(default=2, ge=1)
