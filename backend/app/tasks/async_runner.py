"""Run async coroutines from sync Celery workers without loop-bound client leaks."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


async def _teardown_loop_bound_clients() -> None:
    """Drop Redis + SQLAlchemy pools tied to a closing event loop."""
    from app.db.session import engine
    from app.utils.cache import close_redis_client

    await close_redis_client()
    await engine.dispose()


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """
    Execute *coro* on a fresh event loop.

    Celery prefork workers call many sync tasks that each spin up asyncio via
    ``asyncio.run()`` or ``new_event_loop()``. Module-level Redis and asyncpg
    pools bind to the first loop; once that loop closes, later tasks raise
    "event loop is closed" / "Future attached to a different loop". Reset
    clients before and after each coroutine so every task gets a clean slate.
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_teardown_loop_bound_clients())
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(_teardown_loop_bound_clients())
        except Exception:
            raise
        loop.close()
        asyncio.set_event_loop(None)
