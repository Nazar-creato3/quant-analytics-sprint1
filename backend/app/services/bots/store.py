"""Shared Redis/memory persistence for standalone strategy bots (DCA, momentum)."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.utils.cache import cache_get, cache_set

try:
    from app.services.portfolio.user_scope import filter_grid_bots_for_user
except Exception:  # pragma: no cover - fallback if scope helper is unavailable
    def filter_grid_bots_for_user(bots: dict[str, dict], email: str) -> dict[str, dict]:
        wanted = (email or "").lower()
        return {
            bot_id: data
            for bot_id, data in bots.items()
            if not data.get("created_by") or str(data.get("created_by")).lower() == wanted
        }

logger = get_logger(__name__)

BOT_TTL_SECONDS = 60 * 60 * 24 * 30


async def load_bots(redis_key: str, memory: dict[str, dict]) -> dict[str, dict]:
    raw = await cache_get(redis_key)
    if raw is not None:
        memory.clear()
        memory.update(raw)
        return raw
    return dict(memory)


async def save_bots(redis_key: str, memory: dict[str, dict], bots: dict[str, dict]) -> None:
    memory.clear()
    memory.update(bots)
    ok = await cache_set(redis_key, bots, ttl=BOT_TTL_SECONDS)
    if not ok:
        logger.warning(
            "Redis unavailable — strategy bots persisted in memory only",
            redis_key=redis_key,
            bot_count=len(bots),
        )


async def load_user_bots(redis_key: str, memory: dict[str, dict], email: str) -> dict[str, dict]:
    return filter_grid_bots_for_user(await load_bots(redis_key, memory), email)


def assert_bot_owner(data: dict[str, Any], email: str) -> None:
    from fastapi import HTTPException, status

    owner = (data.get("created_by") or "").lower()
    if owner and owner != email.lower():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
