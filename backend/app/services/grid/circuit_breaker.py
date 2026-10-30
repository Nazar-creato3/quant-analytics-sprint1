"""Pump/dump circuit breaker — pause grid on violent short-window moves."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque


class CircuitState(str, Enum):
    NORMAL = "normal"
    PAUSED = "paused"
    COOLDOWN = "cooldown"


@dataclass
class CircuitBreakerEvent:
    ts: datetime
    event: str  # "pause" | "resume"
    price: float
    move_pct: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "event": self.event,
            "price": round(self.price, 6),
            "move_pct": round(self.move_pct, 4),
            "reason": self.reason,
        }


@dataclass
class PumpDumpCircuitBreaker:
    """
    Monitors rolling short-window price change.
    Pauses new order placement if pump/dump threshold breached;
    resumes once volatility normalizes.
    """

    threshold_pct: float = 5.0
    window_seconds: float = 300.0
    cooldown_seconds: float = 600.0
    resume_threshold_pct: float = 2.0
    state: CircuitState = CircuitState.NORMAL
    paused_at: datetime | None = None
    _history: Deque[tuple[datetime, float]] = field(default_factory=deque)
    _events: list[CircuitBreakerEvent] = field(default_factory=list)

    def _prune(self, now: datetime) -> None:
        cutoff = now.timestamp() - self.window_seconds
        while self._history and self._history[0][0].timestamp() < cutoff:
            self._history.popleft()

    def _rolling_move_pct(self, now: datetime, current_price: float) -> float:
        if not self._history or current_price <= 0:
            return 0.0
        oldest_ts, oldest_price = self._history[0]
        if oldest_price <= 0:
            return 0.0
        return abs(current_price - oldest_price) / oldest_price * 100.0

    def on_price(self, price: float, ts: datetime | None = None) -> CircuitBreakerEvent | None:
        """
        Feed a price tick. Returns an event if state changed (pause/resume), else None.
        """
        now = ts or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        self._history.append((now, price))
        self._prune(now)
        move_pct = self._rolling_move_pct(now, price)

        if self.state == CircuitState.PAUSED:
            elapsed = (now - self.paused_at).total_seconds() if self.paused_at else 0
            if elapsed >= self.cooldown_seconds and move_pct <= self.resume_threshold_pct:
                self.state = CircuitState.NORMAL
                self.paused_at = None
                ev = CircuitBreakerEvent(
                    ts=now, event="resume", price=price, move_pct=move_pct,
                    reason=f"volatility normalized ({move_pct:.2f}% ≤ {self.resume_threshold_pct}%)",
                )
                self._events.append(ev)
                return ev
            return None

        if move_pct >= self.threshold_pct:
            self.state = CircuitState.PAUSED
            self.paused_at = now
            ev = CircuitBreakerEvent(
                ts=now, event="pause", price=price, move_pct=move_pct,
                reason=f"pump/dump detected ({move_pct:.2f}% in {self.window_seconds:.0f}s window)",
            )
            self._events.append(ev)
            return ev

        return None

    def allows_new_orders(self) -> bool:
        return self.state == CircuitState.NORMAL

    def recent_events(self, limit: int = 10) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events[-limit:]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "threshold_pct": self.threshold_pct,
            "window_seconds": self.window_seconds,
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
            "allows_new_orders": self.allows_new_orders(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PumpDumpCircuitBreaker:
        cb = cls(
            threshold_pct=float(data.get("threshold_pct", 5.0)),
            window_seconds=float(data.get("window_seconds", 300.0)),
            cooldown_seconds=float(data.get("cooldown_seconds", 600.0)),
            resume_threshold_pct=float(data.get("resume_threshold_pct", 2.0)),
        )
        state = data.get("state", "normal")
        cb.state = CircuitState(state)
        if data.get("paused_at"):
            cb.paused_at = datetime.fromisoformat(data["paused_at"])
        return cb
