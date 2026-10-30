"""One in-flight fetch per instrument set, short TTL (Prompt 42)."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

FetchMany = Callable[[list[str]], Awaitable[dict[str, Any]]]

_TTL_SEC = 4.0


class QuoteHub:
    def __init__(self, ttl_sec: float = _TTL_SEC) -> None:
        self._inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._ttl = ttl_sec
        self.fetch_counts: dict[str, int] = {}

    async def fetch_many(self, symbols: list[str], fetcher: FetchMany) -> dict[str, Any]:
        key = ",".join(sorted({s.strip().upper() for s in symbols if s.strip()}))
        if not key:
            return {}
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self._ttl:
            return dict(cached[1])
        existing = self._inflight.get(key)
        if existing is not None:
            return dict(await existing)

        async def _run() -> dict[str, Any]:
            self.fetch_counts[key] = self.fetch_counts.get(key, 0) + 1
            payload = await fetcher(key.split(","))
            self._cache[key] = (time.monotonic(), payload)
            return payload

        task = asyncio.create_task(_run())
        self._inflight[key] = task
        try:
            return dict(await task)
        finally:
            if self._inflight.get(key) is task:
                del self._inflight[key]


hub = QuoteHub()
