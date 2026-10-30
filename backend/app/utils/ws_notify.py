"""
Sync wrapper for WebSocket notifications from Celery workers and REST handlers.
"""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger

logger = get_logger(__name__)


def _run(coro) -> None:
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()
    except Exception as exc:
        logger.warning("WS notify failed", error=str(exc))


def notify_pipeline_sync(event_type: str, payload: dict) -> None:
    from app.api.v1.endpoints.websocket import notify_pipeline_event
    from app.services.event_bus.bus import publish_event
    from app.services.event_bus.types import EVENT_NAMES

    if event_type in EVENT_NAMES:
        try:
            publish_event(event_type, payload)
        except Exception:
            logger.debug("event_bus pipeline skip")
    _run(notify_pipeline_event(event_type, payload))


def notify_cockpit_sync(symbol: str, payload: dict) -> None:
    from app.api.v1.endpoints.websocket import notify_cockpit_event
    from app.services.event_bus.bus import publish_event

    if symbol == "BOT_RISK" or (payload or {}).get("event") == "circuit_breaker":
        try:
            publish_event(
                "bot.circuit_breaker",
                {**payload, "symbol": symbol},
            )
        except Exception:
            logger.debug("event_bus cockpit skip")
    _run(notify_cockpit_event(symbol, payload))


def notify_chat_sync(conversation_id: str, payload: dict) -> None:
    from app.api.v1.endpoints.websocket import notify_chat_event

    _run(notify_chat_event(conversation_id, payload))
