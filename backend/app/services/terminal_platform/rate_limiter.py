"""Simple async token-bucket rate limiter."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.services.terminal_platform.types import RateLimitConfig


class RateLimiter:
    """Per-provider rate limiter. No-op when config is empty."""

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config
        self._lock = asyncio.Lock()
        self._tokens = float(config.burst_size) if config else 0.0
        self._last_refill = time.monotonic()
        self._minute_timestamps: list[float] = []
        self._day_timestamps: list[float] = []

    @property
    def enabled(self) -> bool:
        return self.config is not None and (
            self.config.requests_per_second is not None
            or self.config.requests_per_minute is not None
            or self.config.requests_per_day is not None
        )

    def _refill(self) -> None:
        if not self.config or self.config.requests_per_second is None:
            return
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(
            float(self.config.burst_size),
            self._tokens + elapsed * self.config.requests_per_second,
        )

    async def acquire(self, timeout: float = 5.0) -> bool:
        """Return True if a request slot was acquired, False if timed out."""
        if not self.enabled or self.config is None:
            return True

        deadline = time.monotonic() + timeout
        while True:
            async with self._lock:
                self._refill()
                now = time.monotonic()
                # prune windows
                self._minute_timestamps = [t for t in self._minute_timestamps if now - t < 60]
                self._day_timestamps = [t for t in self._day_timestamps if now - t < 86400]

                ok_rps = True
                if self.config.requests_per_second is not None:
                    ok_rps = self._tokens >= 1.0

                ok_rpm = True
                if self.config.requests_per_minute is not None:
                    ok_rpm = len(self._minute_timestamps) < self.config.requests_per_minute

                ok_rpd = True
                if self.config.requests_per_day is not None:
                    ok_rpd = len(self._day_timestamps) < self.config.requests_per_day

                if ok_rps and ok_rpm and ok_rpd:
                    if self.config.requests_per_second is not None:
                        self._tokens -= 1.0
                    self._minute_timestamps.append(now)
                    self._day_timestamps.append(now)
                    return True

            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)
