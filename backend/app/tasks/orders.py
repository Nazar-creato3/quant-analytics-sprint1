"""Celery tasks for manual conditional order polling (spec B.2)."""
from __future__ import annotations

from app.db.session import AsyncSessionLocal
from app.services.orders.conditional_manager import poll_conditional_orders
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.orders.poll_conditional_orders_task")
def poll_conditional_orders_task() -> dict[str, int]:
    """Poll OCO/trailing/stop watchers and submit broker orders when triggered."""

    async def _run() -> dict[str, int]:
        async with AsyncSessionLocal() as db:
            triggered = await poll_conditional_orders(db)
            return {"triggered": triggered}

    return run_async(_run())
