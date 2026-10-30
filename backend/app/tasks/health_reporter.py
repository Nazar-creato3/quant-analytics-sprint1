"""Celery task: hourly health reporter to Telegram."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.health_reporter.run_hourly_health_report_task")
def run_hourly_health_report_task() -> dict[str, Any]:
    return run_async(_async_run())


async def _async_run() -> dict[str, Any]:
    from app.services.health.reporter import run_health_report

    return await run_health_report(send_telegram=True)
