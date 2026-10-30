"""Typed event names (Prompt 07). Schema version is on the envelope."""
from __future__ import annotations

EVENT_NAMES = (
    "position.changed",
    "order.filled",
    "order.rejected",
    "risk.limit_breached",
    "risk.warning",
    "bot.paused",
    "bot.circuit_breaker",
    "forecast.updated",
    "maneuver.created",
    "maneuver.approved",
    "account.synced",
    "account.sync_failed",
    "report.ready",
    "subscription.changed",
    "data.quality_failed",
    "regime.changed",
)

SCHEMA_VERSION = 1
