"""Celery tasks for EventRiskLayer polling."""
from __future__ import annotations

from app.db.session import AsyncSessionLocal
from app.services.event_risk import get_event_risk_layer
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.event_risk.process_event_risk_task")
def process_event_risk_task() -> dict[str, int]:
    """Poll news/calendar streams and apply TTL locks when news_shock breaches threshold."""

    async def _run() -> dict[str, int]:
        layer = get_event_risk_layer()
        async with AsyncSessionLocal() as db:
            expired = await layer.expire_stale_locks(db)
            triggered = await layer.process_cycle(db)
            await db.commit()
            return {"expired": expired, "triggered": len(triggered)}

    return run_async(_run())


@celery_app.task(name="app.tasks.event_risk.process_news_impact_feedback_task")
def process_news_impact_feedback_task() -> dict[str, int]:
    """Reconcile predicted news impact with realized price moves."""

    async def _run() -> dict[str, int]:
        layer = get_event_risk_layer()
        async with AsyncSessionLocal() as db:
            updated = await layer.process_feedback(db)
            await db.commit()
            return {"updated": updated}

    return run_async(_run())
