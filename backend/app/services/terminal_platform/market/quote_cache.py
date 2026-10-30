"""Shared quote cache + upstream rate guards for Terminal market data."""
from __future__ import annotations

from typing import Any, Optional

from app.core.logging import get_logger
from app.utils.cache import cache_get, cache_set, rate_limit_check

logger = get_logger(__name__)

# Short TTL — shared across all users/devices on the same VPS.
KEYED_QUOTE_TTL_SEC = 45
INDICES_CACHE_TTL_SEC = 30

# Finnhub free tier ≈ 60 req/min; stay conservative across 4 uvicorn workers.
FINNHUB_GLOBAL_LIMIT_PER_MIN = 25


def keyed_quote_cache_key(provider: str, symbol: str) -> str:
    return f"terminal:eq_quote:{provider}:{symbol.strip().upper()}"


async def get_cached_keyed_quote(provider: str, symbol: str) -> Optional[dict[str, Any]]:
    hit = await cache_get(keyed_quote_cache_key(provider, symbol))
    return hit if isinstance(hit, dict) else None


async def set_cached_keyed_quote(provider: str, symbol: str, payload: dict[str, Any]) -> None:
    await cache_set(keyed_quote_cache_key(provider, symbol), payload, ttl=KEYED_QUOTE_TTL_SEC)


async def finnhub_upstream_allowed() -> bool:
    """Global Finnhub budget — prevents parallel index fetches from tripping 429."""
    allowed, _ = await rate_limit_check(
        "upstream:finnhub",
        FINNHUB_GLOBAL_LIMIT_PER_MIN,
        60,
        fail_closed=False,
    )
    if not allowed:
        logger.info("Finnhub global budget exhausted — skipping to fallbacks")
    return allowed
