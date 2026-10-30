"""In-memory + Redis cache for terminal ProviderRouter."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


class TerminalCache:
    """
    Two-tier cache: process memory first, Redis second.

    Redis failures never raise — callers always get a graceful miss.
    """

    def __init__(self, *, default_ttl_seconds: int = 120, prefix: str = "terminal:"):
        self.default_ttl = default_ttl_seconds
        self.prefix = prefix
        self._memory: dict[str, tuple[float, Any]] = {}

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def get_memory(self, key: str) -> Optional[Any]:
        full = self._full_key(key)
        entry = self._memory.get(full)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            self._memory.pop(full, None)
            return None
        return value

    def set_memory(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        full = self._full_key(key)
        self._memory[full] = (time.time() + (ttl or self.default_ttl), value)

    async def get(self, key: str) -> Optional[Any]:
        mem = self.get_memory(key)
        if mem is not None:
            return mem
        try:
            from app.utils.cache import cache_get

            value = await cache_get(self._full_key(key))
            if value is not None:
                self.set_memory(key, value)
            return value
        except Exception as exc:
            logger.debug("terminal cache redis get failed", error=str(exc))
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expire = ttl or self.default_ttl
        self.set_memory(key, value, expire)
        try:
            from app.utils.cache import cache_set

            # Ensure JSON-serializable for Redis path.
            payload = json.loads(json.dumps(value, default=str))
            await cache_set(self._full_key(key), payload, ttl=expire)
        except Exception as exc:
            logger.debug("terminal cache redis set failed", error=str(exc))

    def clear_memory(self) -> None:
        self._memory.clear()
