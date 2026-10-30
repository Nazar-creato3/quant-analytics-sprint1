"""Redis cache for PredictionHierarchyOrchestrator (Prompt 38)."""
from __future__ import annotations

from app.utils.cache import cache_get, cache_set

# Daily-bar hierarchy is stable for hours; 15s made pipeline hints almost always miss.
FORECAST_CACHE_TTL_SECONDS = 4 * 60 * 60


def forecast_cache_key(instrument_id: int, portfolio_hash: str = "none") -> str:
    return f"prediction_hierarchy:forecast:{instrument_id}:{portfolio_hash}"


async def get_cached_forecast(instrument_id: int, portfolio_hash: str = "none") -> dict | None:
    payload = await cache_get(forecast_cache_key(instrument_id, portfolio_hash))
    if isinstance(payload, dict):
        return payload
    return None


async def set_cached_forecast(
    instrument_id: int,
    payload: dict,
    *,
    portfolio_hash: str = "none",
    ttl: int = FORECAST_CACHE_TTL_SECONDS,
) -> None:
    await cache_set(forecast_cache_key(instrument_id, portfolio_hash), payload, ttl=ttl)
