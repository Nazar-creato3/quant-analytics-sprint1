"""Shared helpers for terminal data providers."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

# Soft codes: skip provider / try next — must NOT trip circuit breakers.
SOFT_PROVIDER_ERROR_CODES = frozenset(
    {
        "KEY_MISSING",
        "UNSUPPORTED",
        "RATE_LIMIT",
        "CIRCUIT_OPEN",
        "EMPTY",
        "TIMEOUT",
        "CLIENT_REJECT",
        "PROXY",
        "DEPENDENCY_MISSING",
        "TRANSIENT",
    }
)


def classify_provider_error(error: Any) -> str:
    """
    Map exceptions / messages to FetchResult error_code.

    Soft classifications (unsupported symbol, 429, proxy timeout, missing optional
    dependency) must not sticky-open circuits or mark the provider degraded.
    """
    if isinstance(error, (ModuleNotFoundError, ImportError)):
        return "DEPENDENCY_MISSING"
    if isinstance(error, (TimeoutError,)):
        return "TIMEOUT"
    msg = str(error or "").lower()
    if not msg:
        return "PROVIDER_ERROR"
    if "no module named" in msg or "cannot import name" in msg:
        return "DEPENDENCY_MISSING"
    if (
        "429" in msg
        or "too many requests" in msg
        or "rate limit" in msg
        or "rate_limit" in msg
        or "spread out your" in msg
        or "requests per day" in msg
        or "thank you for using alpha vantage" in msg
    ):
        return "RATE_LIMIT"
    if (
        "401" in msg
        or "403" in msg
        or "forbidden" in msg
        or "unauthorized" in msg
        or "invalid api key" in msg
        or "not entitled" in msg
    ):
        return "CLIENT_REJECT"
    if (
        "400" in msg
        or "bad request" in msg
        or "invalid symbol" in msg
        or "unknown symbol" in msg
        or "symbol not found" in msg
        or "unsupported symbol" in msg
    ):
        return "UNSUPPORTED"
    if (
        "timeout" in msg
        or "timed out" in msg
        or "deadline exceeded" in msg
        or "read timed out" in msg
    ):
        return "TIMEOUT"
    if (
        "proxy" in msg
        or "could not connect" in msg
        or "connection refused" in msg
        or "connection reset" in msg
        or "failed to connect" in msg
        or "network is unreachable" in msg
        or "temporarily unavailable" in msg
        or "name or service not known" in msg
    ):
        return "PROXY"
    return "PROVIDER_ERROR"


def to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if value is None:
        return datetime.now(timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
