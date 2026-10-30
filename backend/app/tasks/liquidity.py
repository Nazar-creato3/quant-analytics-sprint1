"""Celery tasks for LiquidityMonitor polling."""
from __future__ import annotations

from app.db.session import AsyncSessionLocal
from app.services.liquidity import get_liquidity_monitor
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.liquidity.process_liquidity_monitor_task")
def process_liquidity_monitor_task() -> dict[str, int]:
    """Evaluate order book depth/spread/volume and apply drought locks."""

    async def _run() -> dict[str, int]:
        monitor = get_liquidity_monitor()
        async with AsyncSessionLocal() as db:
            result = await monitor.process_cycle(db)
            await db.commit()
            return result

    return run_async(_run())
