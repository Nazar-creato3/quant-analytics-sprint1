"""Nightly FRED macro cache sync (free; needs FRED_API_KEY)."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.fred_bulk.sync_fred_bulk_task")
def sync_fred_bulk_task() -> dict[str, Any]:
    try:
        result = run_async(_async_sync())
        logger.info(
            "fred_bulk_sync_done",
            ok=result.get("ok"),
            series=result.get("series_count"),
            status=result.get("status"),
        )
        return result
    except Exception as exc:
        logger.exception("fred_bulk_sync_failed", error=str(exc)[:200])
        return {"ok": False, "status": "failed", "error": str(exc)[:200]}


async def _async_sync() -> dict[str, Any]:
    from app.services.market_data.fred_bulk_store import store_status, sync_fred_bulk

    before = store_status()
    result = await sync_fred_bulk()
    result["before"] = before
    return result
