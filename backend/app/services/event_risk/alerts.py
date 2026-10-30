"""Alerts for major news_shock lock triggers and generic ops webhooks."""
from __future__ import annotations

import os

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.services.alerts.telegram import send_telegram_message
from app.services.event_risk.types import NewsShockAssessment

logger = structlog.get_logger(__name__)
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def emit_ops_alert(
    *,
    event: str,
    message: str,
    payload: dict | None = None,
    settings: Settings | None = None,
) -> None:
    """Send Slack-compatible webhook alert, else Telegram, else structlog."""
    cfg = settings or get_settings()
    extra = {"alert_event": event, "text": message, **(payload or {})}

    webhook_url = (os.environ.get("SLACK_WEBHOOK_URL") or cfg.ALERT_WEBHOOK_URL or "").strip()
    if webhook_url:
        slack_payload = {
            "text": message,
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": message}}],
            **extra,
        }
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(webhook_url, json=slack_payload)
                response.raise_for_status()
            logger.info("alert_webhook_sent", **extra)
            return
        except Exception as exc:
            logger.warning("alert_webhook_failed", error=str(exc), **extra)

    if cfg.telegram_configured:
        sent = await send_telegram_message(cfg.TELEGRAM_CHAT_ID, message, settings=cfg)
        if sent:
            logger.info("telegram_alert_sent", **extra)
            return
        logger.warning("telegram_alert_failed", **extra)

    # Silent when no webhook/telegram configured (founder: unset = no noise).
    if not webhook_url and not cfg.telegram_configured:
        logger.debug("ops_alert_skipped_no_channel", **extra)
        return
    logger.warning("ops_alert", **extra)


async def emit_news_shock_alert(
    assessment: NewsShockAssessment,
    *,
    settings: Settings | None = None,
) -> None:
    """Send alert when a news_shock lock triggers."""
    payload = {
        "symbol": assessment.target.symbol,
        "instrument_id": assessment.target.instrument_id,
        "sector": assessment.target.sector,
        "news_shock_score": assessment.score,
        "reason": assessment.reason,
        "source_event_id": assessment.source_event_id,
    }
    message = (
        f"Apex Intel news_shock lock\n"
        f"Symbol: {assessment.target.symbol}\n"
        f"Score: {assessment.score:.3f}\n"
        f"Reason: {assessment.reason}"
    )
    await emit_ops_alert(
        event="news_shock_lock_triggered",
        message=message,
        payload=payload,
        settings=settings,
    )


async def emit_quality_gate_alert(
    *,
    source_id: str,
    failure_count: int,
    module: str = "macro_quality_gate",
    settings: Settings | None = None,
) -> None:
    """Alert on systematic quality-gate failures (MacroRegistry, etc.)."""
    message = (
        f"Apex Intel quality gate failure\n"
        f"Module: {module}\n"
        f"Source: {source_id}\n"
        f"Consecutive failures: {failure_count}"
    )
    await emit_ops_alert(
        event=f"{module}_systematic_failure",
        message=message,
        payload={"source_id": source_id, "failure_count": failure_count, "module": module},
        settings=settings,
    )


async def emit_diagnostics_alert(
    *,
    check_id: str,
    message: str,
    context: dict | None = None,
    settings: Settings | None = None,
) -> None:
    """Alert when DiagnosticsEngine invariant or golden check fails."""
    detail = f"Apex Intel diagnostics failed\nCheck: {check_id}\n{message}"
    await emit_ops_alert(
        event="diagnostics_invariant_failed",
        message=detail,
        payload={"check_id": check_id, "context": context or {}},
        settings=settings,
    )
