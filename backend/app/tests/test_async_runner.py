"""Tests for Celery async runner (loop-bound client teardown)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_close_redis_client_clears_pool() -> None:
    import app.utils.cache as cache_mod

    mock_redis = AsyncMock()
    cache_mod._redis_pool = mock_redis

    await cache_mod.close_redis_client()

    mock_redis.aclose.assert_awaited_once()
    assert cache_mod._redis_pool is None


def test_run_async_survives_back_to_back_calls() -> None:
    from app.tasks.async_runner import run_async

    async def _touch_clients() -> str:
        from app.utils.cache import cache_get

        await cache_get("grid:bots")
        return "ok"

    with patch("app.utils.cache._get_redis") as mock_get_redis:
        redis_client = AsyncMock()
        redis_client.get = AsyncMock(return_value=None)
        mock_get_redis.return_value = redis_client

        assert run_async(_touch_clients()) == "ok"
        assert run_async(_touch_clients()) == "ok"

    assert mock_get_redis.call_count == 2
