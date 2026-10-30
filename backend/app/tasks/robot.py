"""Celery tasks for Robot Core level monitor + funding/fees sync."""
from __future__ import annotations

from typing import Any

from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="app.tasks.robot.tick_robot_levels_task")
def tick_robot_levels_task(self) -> dict[str, Any]:
    task_id = str(getattr(self.request, "id", "") or "")
    return run_async(_async_tick(task_id))


async def _async_tick(celery_task_id: str = "") -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.robot.monitor import tick_robot_plans

    async with AsyncSessionLocal() as session:
        return await tick_robot_plans(session, celery_task_id=celery_task_id)


@celery_app.task(name="app.tasks.robot.sync_funding_task")
def sync_funding_task() -> dict[str, Any]:
    return run_async(_async_funding())


async def _async_funding() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.robot.funding import sync_funding_from_open_lots

    async with AsyncSessionLocal() as session:
        return await sync_funding_from_open_lots(session)


@celery_app.task(name="app.tasks.robot.sync_venue_fees_task")
def sync_venue_fees_task() -> dict[str, Any]:
    return run_async(_async_fees())


async def _async_fees() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.robot.fees import sync_venue_fees

    async with AsyncSessionLocal() as session:
        return await sync_venue_fees(session)
