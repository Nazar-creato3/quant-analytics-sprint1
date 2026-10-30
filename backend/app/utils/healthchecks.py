"""Healthchecks.io ping helpers for scheduled job dead-man's switch (Prompt 2)."""
from __future__ import annotations

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def ping_healthcheck(url: str | None, *, success: bool = True) -> None:
    """GET ping URL; append /fail when success=False."""
    base = (url or "").strip()
    if not base:
        return
    target = base if success else f"{base.rstrip('/')}/fail"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(target)
            resp.raise_for_status()
        logger.info("healthcheck_ping_ok", url=base[:48], success=success)
    except Exception as exc:
        logger.warning("healthcheck_ping_failed", url=base[:48], success=success, error=str(exc))
