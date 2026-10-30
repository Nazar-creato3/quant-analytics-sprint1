"""Circuit breaker for individual data providers."""
from __future__ import annotations

import time
from enum import Enum
from typing import Optional

from app.services.terminal_platform.types import CircuitBreakerConfig


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Fail-fast after consecutive provider errors; recover after cool-down."""

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.opened_at: Optional[float] = None
        self._half_open_calls = 0

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self.opened_at is None:
                return False
            if time.monotonic() - self.opened_at >= self.config.recovery_timeout_seconds:
                self.state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                return True
            return False
        if self._half_open_calls < self.config.half_open_max_calls:
            self._half_open_calls += 1
            return True
        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.success_count += 1
        self.state = CircuitState.CLOSED
        self.opened_at = None
        self._half_open_calls = 0

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.state == CircuitState.HALF_OPEN:
            self._trip()
            return
        if self.failure_count >= self.config.failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self.state = CircuitState.OPEN
        self.opened_at = time.monotonic()
        self._half_open_calls = 0

    def reset(self) -> None:
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at = None
        self._half_open_calls = 0
