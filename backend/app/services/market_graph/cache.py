"""Redis cache helpers for MarketGraph read queries."""
from __future__ import annotations

from app.utils.cache import cache_delete_pattern, cache_get, cache_set


def cluster_cache_key(instrument_id: int, threshold: float) -> str:
    return f"market_graph:cluster:{instrument_id}:{threshold:.4f}"


def sector_context_cache_key(instrument_id: int) -> str:
    return f"market_graph:sector_ctx:{instrument_id}"


async def get_cached_cluster(instrument_id: int, threshold: float) -> list[int] | None:
    payload = await cache_get(cluster_cache_key(instrument_id, threshold))
    if payload is None:
        return None
    if not isinstance(payload, list):
        return None
    return [int(value) for value in payload]


async def set_cached_cluster(
    instrument_id: int,
    threshold: float,
    cluster: list[int],
    *,
    ttl: int,
) -> None:
    await cache_set(cluster_cache_key(instrument_id, threshold), cluster, ttl=ttl)


async def get_cached_sector_context(instrument_id: int) -> dict | None:
    payload = await cache_get(sector_context_cache_key(instrument_id))
    if isinstance(payload, dict):
        return payload
    return None


async def set_cached_sector_context(
    instrument_id: int,
    payload: dict,
    *,
    ttl: int,
) -> None:
    await cache_set(sector_context_cache_key(instrument_id), payload, ttl=ttl)


async def invalidate_market_graph_cache() -> None:
    await cache_delete_pattern("market_graph:*")
