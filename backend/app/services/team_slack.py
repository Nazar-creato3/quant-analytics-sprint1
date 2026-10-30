"""Team-only Slack notifications (waitlist, support, incidents)."""
from __future__ import annotations

import os

from app.core.config import get_settings
from app.services.event_risk.alerts import emit_ops_alert

TEAM_EVENTS = frozenset({"waitlist", "support", "incident"})


async def notify_team(event: str, message: str, payload: dict | None = None) -> None:
    if event not in TEAM_EVENTS:
        return
    if not (os.environ.get("SLACK_WEBHOOK_URL") or "").strip():
        # Still allow ALERT_WEBHOOK_URL via emit_ops_alert fallback.
        settings = get_settings()
        if not (settings.ALERT_WEBHOOK_URL or "").strip():
            return
    settings = get_settings()
    await emit_ops_alert(event=event, message=message, payload=payload, settings=settings)
