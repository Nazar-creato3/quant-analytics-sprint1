"""Nightly equity EOD board cache (Tiingo/Yahoo) — always-on Stooq complement."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.equity_eod.sync_equity_eod_task")
def sync_equity_eod_task() -> dict[str, Any]:
    try:
        result = run_async(_async_sync())
        logger.info(
            "equity_eod_sync_done",
            ok=result.get("ok"),
            symbols=result.get("symbol_count"),
            status=result.get("status"),
        )
        return result
    except Exception as exc:
        logger.exception("equity_eod_sync_failed", error=str(exc)[:200])
        return {"ok": False, "status": "failed", "error": str(exc)[:200]}


async def _async_sync() -> dict[str, Any]:
    from app.services.market_data.equity_eod_store import store_status, sync_equity_eod
    from app.services.market_data.nightly_digest import (
        build_nightly_digest,
        prune_stooq_inbox,
        save_digest,
    )

    before = store_status()
    result = await sync_equity_eod()
    result["before"] = before
    try:
        digest = build_nightly_digest()
        path = save_digest(digest)
        result["digest_path"] = str(path)
        result["digest_coverage"] = digest.get("coverage")
        result["inbox_pruned"] = prune_stooq_inbox(keep_days=2)
    except Exception as exc:
        logger.warning("nightly_digest_failed", error=str(exc)[:200])
        result["digest_error"] = str(exc)[:200]
    return result
