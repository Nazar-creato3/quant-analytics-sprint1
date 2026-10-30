"""Watchlist threshold alerts — Telegram/webhook via existing ops transport."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import WatchlistAlertRule
from app.services.event_risk.alerts import emit_ops_alert
from app.services.instrument.resolver import resolve_or_create_instrument

logger = get_logger(__name__)

_COOLDOWN_HOURS = 6


async def _metric_value(db: AsyncSession, symbol: str, metric: str) -> float | None:
    sym = symbol.upper()
    if metric in ("ml_confidence", "ml_score"):
        try:
            from app.services.prediction_hierarchy.cache import get_cached_forecast

            inst = await resolve_or_create_instrument(db, sym)
            cached = await get_cached_forecast(inst.id)
            if cached:
                conf = cached.get("calibrated_confidence")
                if conf is not None:
                    return float(conf)
        except Exception as exc:
            logger.debug("Alert metric cache miss", symbol=sym, error=str(exc))
        return None
    return None


def _breached(value: float, threshold: float, direction: str) -> bool:
    if direction == "below":
        return value <= threshold
    return value >= threshold


async def evaluate_watchlist_alert_rules(db: AsyncSession) -> dict[str, int]:
    """Check enabled rules; emit ops alert when threshold crossed (with cooldown)."""
    result = await db.execute(
        select(WatchlistAlertRule).where(WatchlistAlertRule.enabled.is_(True))
    )
    rules = list(result.scalars().all())
    triggered = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    for rule in rules:
        value = await _metric_value(db, rule.symbol, rule.metric)
        if value is None:
            skipped += 1
            continue
        if not _breached(value, rule.threshold, rule.direction):
            continue
        if rule.last_triggered_at:
            last = rule.last_triggered_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (now - last).total_seconds() < _COOLDOWN_HOURS * 3600:
                skipped += 1
                continue

        message = (
            f"Watchlist alert: {rule.symbol} {rule.metric}={value:.2f} "
            f"({rule.direction} {rule.threshold:.2f}) for {rule.user_email}"
        )
        await emit_ops_alert(
            event="watchlist_threshold",
            message=message,
            payload={
                "symbol": rule.symbol,
                "metric": rule.metric,
                "value": value,
                "threshold": rule.threshold,
                "user_email": rule.user_email,
            },
        )
        rule.last_triggered_at = now
        triggered += 1

    if triggered:
        await db.commit()
    return {"checked": len(rules), "triggered": triggered, "skipped": skipped}
