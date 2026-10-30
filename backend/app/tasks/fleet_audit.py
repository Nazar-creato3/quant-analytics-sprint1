"""Nightly admin fleet snapshot — internal books only."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.fleet_audit.refresh_fleet_audit_task")
def refresh_fleet_audit_task() -> dict[str, Any]:
    return run_async(_async_refresh())


async def _async_refresh() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.audit.fleet import refresh_fleet_snapshot

    async with AsyncSessionLocal() as session:
        snap = await refresh_fleet_snapshot(session)
    logger.info(
        "fleet_audit_refreshed",
        users=snap.get("user_count"),
        open_maneuvers=snap.get("open_maneuver_count"),
    )
    return {
        "status": "ok",
        "as_of": snap.get("as_of"),
        "user_count": snap.get("user_count"),
        "feeds_maneuver_factory": False,
    }
