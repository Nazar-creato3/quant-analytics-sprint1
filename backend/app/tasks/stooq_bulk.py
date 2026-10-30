"""Nightly Stooq bulk ZIP sync → local OHLCV store for charts/markets/robots."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.stooq_bulk.sync_stooq_bulk_task")
def sync_stooq_bulk_task() -> dict[str, Any]:
    """Download/ingest Stooq daily ASCII packs into STOOQ_BULK_DIR."""
    try:
        result = run_async(_async_sync())
        logger.info(
            "stooq_bulk_sync_done",
            ok=result.get("ok"),
            symbols=result.get("symbols") or result.get("symbol_count"),
            status=result.get("status"),
        )
        return result
    except Exception as exc:
        logger.exception("stooq_bulk_sync_failed", error=str(exc)[:200])
        return {"ok": False, "status": "failed", "error": str(exc)[:200]}


async def _async_sync() -> dict[str, Any]:
    from app.services.market_data.stooq_bulk_store import store_status, sync_stooq_bulk

    before = store_status()
    result = await sync_stooq_bulk(prefer_download=True)
    result["before"] = before
    return result
