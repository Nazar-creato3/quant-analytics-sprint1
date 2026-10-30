"""In-process event bus with outbox, ack, retry, DLQ, idempotent handlers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from app.services.event_bus.types import EVENT_NAMES, SCHEMA_VERSION
from app.services.qa.feature_flags import is_enabled

Handler = Callable[[dict[str, Any]], None]


@dataclass
class Envelope:
    id: str
    name: str
    payload: dict[str, Any]
    schema_version: int
    published_at: datetime
    attempts: int = 0
    idempotency_key: str = ""


@dataclass
class EventBus:
    _outbox: list[Envelope] = field(default_factory=list)
    _stream: list[Envelope] = field(default_factory=list)
    _pending: dict[str, Envelope] = field(default_factory=dict)
    _dlq: list[Envelope] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)
    _handlers: dict[str, list[Handler]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)
    max_attempts: int = 3

    def publish(self, name: str, payload: dict[str, Any], *, idempotency_key: str | None = None) -> Envelope | None:
        if name not in EVENT_NAMES:
            raise ValueError(f"unknown event {name}")
        if not is_enabled("qa_event_bus"):
            return None
        key = idempotency_key or str(payload.get("idempotency_key") or uuid4())
        with self._lock:
            if key in self._seen:
                return next((e for e in self._stream if e.idempotency_key == key), None)
            env = Envelope(
                id=str(uuid4()),
                name=name,
                payload=dict(payload),
                schema_version=SCHEMA_VERSION,
                published_at=datetime.now(timezone.utc),
                idempotency_key=key,
            )
            self._outbox.append(env)
            self._stream.append(env)
            self._pending[env.id] = env
            self._seen.add(key)
        _ensure_default_handlers(self)
        self._dispatch(env)
        return env

    def subscribe(self, name: str, handler: Handler) -> None:
        with self._lock:
            self._handlers.setdefault(name, []).append(handler)

    def ack(self, event_id: str) -> None:
        with self._lock:
            self._pending.pop(event_id, None)

    def fail(self, event_id: str) -> None:
        with self._lock:
            env = self._pending.get(event_id)
            if env is None:
                return
            env.attempts += 1
            if env.attempts >= self.max_attempts:
                self._dlq.append(env)
                self._pending.pop(event_id, None)

    def redeliver_pending(self) -> int:
        with self._lock:
            pending = list(self._pending.values())
        n = 0
        for env in pending:
            self._dispatch(env)
            n += 1
        return n

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return {
                "outbox": len(self._outbox),
                "stream": len(self._stream),
                "pending": len(self._pending),
                "dlq": len(self._dlq),
            }

    def reset(self) -> None:
        global _defaults_on
        with self._lock:
            self._outbox.clear()
            self._stream.clear()
            self._pending.clear()
            self._dlq.clear()
            self._seen.clear()
            self._handlers.clear()
        _defaults_on = False

    def _dispatch(self, env: Envelope) -> None:
        handlers = list(self._handlers.get(env.name) or [])
        failed = False
        for handler in handlers:
            try:
                handler({"id": env.id, "name": env.name, "payload": env.payload, "schema_version": env.schema_version})
            except Exception:
                failed = True
        if failed:
            self.fail(env.id)
        else:
            self.ack(env.id)


_BUS = EventBus()
_defaults_on = False


def _ensure_default_handlers(bus: EventBus) -> None:
    global _defaults_on
    if _defaults_on:
        return
    from app.services.event_bus.notifications import on_bus_event
    from app.services.event_bus.types import EVENT_NAMES

    for name in EVENT_NAMES:
        bus.subscribe(name, on_bus_event)
    _defaults_on = True


def get_bus() -> EventBus:
    return _BUS


def publish_event(name: str, payload: dict[str, Any], *, idempotency_key: str | None = None) -> Envelope | None:
    return get_bus().publish(name, payload, idempotency_key=idempotency_key)
