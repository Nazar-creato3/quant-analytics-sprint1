"""Celery task: evaluate watchlist ML/confidence threshold alerts."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.alerts.check_watchlist_alerts_task")
def check_watchlist_alerts_task() -> dict[str, Any]:
    return run_async(_async_check())


async def _async_check() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.alerts.watchlist_rules import evaluate_watchlist_alert_rules

    async with AsyncSessionLocal() as session:
        stats = await evaluate_watchlist_alert_rules(session)
    logger.info("Watchlist alert check complete", **stats)
    return stats
