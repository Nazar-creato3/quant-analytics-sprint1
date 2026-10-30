"""
Shared utility helpers used across the application.
"""
from __future__ import annotations

import asyncio
import functools
import math
import re
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, TypeVar
from uuid import uuid4

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def new_uuid() -> str:
    """Return a new UUID4 string (shared helper for domain ORMs)."""
    return str(uuid4())


# ── Retry with exponential backoff ────────────────────────────────────────────

def async_retry(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator: retry an async function with exponential backoff.

    Usage:
        @async_retry(max_attempts=3, exceptions=(httpx.RequestError,))
        async def fetch_data(): ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        wait = backoff_base ** attempt
                        logger.warning(
                            "Retrying after error",
                            func=func.__name__,
                            attempt=attempt + 1,
                            wait=wait,
                            error=str(exc),
                        )
                        await asyncio.sleep(wait)
            raise last_exc  # type: ignore
        return wrapper
    return decorator


# ── Pagination helpers ────────────────────────────────────────────────────────

def paginate(
    items: list[T],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Slice a list and return pagination metadata."""
    total = len(items)
    pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size
    return {
        "items": items[offset : offset + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


def chunked(iterable: Iterable[T], size: int) -> list[list[T]]:
    """Split an iterable into chunks of `size`."""
    lst = list(iterable)
    return [lst[i : i + size] for i in range(0, len(lst), size)]


# ── Date/time helpers ─────────────────────────────────────────────────────────

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_to_datetime(s: str) -> datetime:
    """Parse ISO-8601 string to timezone-aware datetime."""
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_currency(value: float, symbol: str = "$") -> str:
    """Format a float as a currency string: $1,234.56"""
    return f"{symbol}{value:,.2f}"


def format_pct(value: float, decimals: int = 1) -> str:
    """Format a float (0.12) as a percentage string: 12.0%"""
    return f"{value * 100:.{decimals}f}%"


# ── Ticker validation ─────────────────────────────────────────────────────────

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")


def validate_ticker(ticker: str) -> str:
    """
    Validate and normalise a ticker symbol.
    Raises ValueError for invalid symbols.
    """
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        raise ValueError(f"Invalid ticker symbol: {ticker!r}")
    return t


def validate_tickers(tickers: list[str]) -> list[str]:
    """Validate and deduplicate a list of tickers. Raises on first invalid."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in tickers:
        t = validate_ticker(raw)
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


# ── Financial math helpers ────────────────────────────────────────────────────

def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def pct_change(old: float, new: float) -> float:
    """Percentage change from old to new. Returns 0 if old == 0."""
    if old == 0:
        return 0.0
    return (new - old) / old


def annualised_return(total_return: float, days: int) -> float:
    """Convert a total return over `days` to an annualised rate."""
    if days <= 0:
        return 0.0
    return (1 + total_return) ** (365 / days) - 1


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Kelly criterion position sizing fraction.
    Capped at 0.25 (quarter-Kelly) for safety.
    """
    if avg_loss == 0:
        return 0.0
    b = abs(avg_win / avg_loss)
    f = (b * win_rate - (1 - win_rate)) / b
    return clamp(f * 0.25, 0.0, 0.25)  # quarter-Kelly, never negative


def sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.05,
    periods_per_year: int = 252,
) -> float:
    """Compute annualised Sharpe ratio from a list of period returns."""
    import numpy as np

    r = np.array(returns)
    if len(r) < 2 or r.std() == 0:
        return 0.0
    excess = r - risk_free_rate / periods_per_year
    return float(excess.mean() / excess.std() * math.sqrt(periods_per_year))


# ── Text helpers ──────────────────────────────────────────────────────────────

def truncate(text: str, max_length: int = 200, suffix: str = "…") -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def slugify(text: str) -> str:
    """Convert a string to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def get_user_settings_key(email: str) -> str:
    """Redis key for per-user settings overrides."""
    return f"settings:user:{email.strip().lower()}"
