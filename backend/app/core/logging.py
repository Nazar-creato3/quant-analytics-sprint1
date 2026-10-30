"""
Structured logging configuration.
Uses structlog for JSON output in production, pretty-print in development.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import AppEnv, settings


_REDACT_FRAGMENTS = ("secret", "password", "token", "api_key", "authorization")


def drop_secret_keys(
    logger: logging.Logger, method: str, event_dict: EventDict
) -> EventDict:
    """Never emit credential-like keys (Prompt 02)."""
    for key in list(event_dict):
        lowered = key.lower()
        if any(fragment in lowered for fragment in _REDACT_FRAGMENTS):
            event_dict[key] = "[redacted]"
    return event_dict


def add_app_context(
    logger: logging.Logger, method: str, event_dict: EventDict
) -> EventDict:
    """Inject app-level context into every log entry."""
    event_dict["app"] = settings.APP_NAME
    event_dict["version"] = settings.APP_VERSION
    event_dict["env"] = settings.APP_ENV.value
    return event_dict


def setup_logging() -> None:
    """Configure structlog + stdlib logging."""
    log_level = settings.LOG_LEVEL.value
    is_dev = settings.APP_ENV == AppEnv.DEVELOPMENT

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        add_app_context,
        drop_secret_keys,
    ]

    if is_dev:
        # plain_traceback: rich tracebacks with locals take ~30 s per error and block the event loop.
        renderer = structlog.dev.ConsoleRenderer(colors=True, exception_formatter=structlog.dev.plain_traceback)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Silence noisy third-party loggers
    # httpx/httpcore log every request URL at INFO, including API keys passed as
    # query parameters (FMP, Polygon, TwelveData): keep them at WARNING.
    for noisy in ["uvicorn.access", "sqlalchemy.engine", "celery", "httpx", "httpcore"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a bound logger for a module."""
    return structlog.get_logger(name)
