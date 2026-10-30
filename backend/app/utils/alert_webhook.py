"""Generic Slack-compatible alert webhook helper."""
from __future__ import annotations

import httpx
import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def emit_alert_webhook(
    title: str,
    payload: dict,
    *,
    settings: Settings | None = None,
) -> bool:
    """Post JSON alert to configured webhook URL. Returns True if delivered."""
    cfg = settings or get_settings()
    url = (cfg.WEBHOOK_URL or "").strip()
    if not url:
        logger.warning("alert_webhook_skipped", title=title, reason="WEBHOOK_URL not configured")
        return False

    body = {"text": title, "attachments": [{"fields": [{"title": k, "value": str(v), "short": True} for k, v in payload.items()]}]}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
        logger.info("alert_webhook_sent", title=title)
        return True
    except Exception as exc:
        logger.warning("alert_webhook_failed", title=title, error=str(exc))
        return False
