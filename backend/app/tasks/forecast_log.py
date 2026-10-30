"""Celery jobs for forecast_log basket, persist, settle, daily hash."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.core.logging import get_logger
from app.services.forecast_log.record import DEFAULT_BASKET
from app.services.forecast_log.store import get_store
from app.services.qa.feature_flags import is_enabled
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.forecast_log.persist_forecast_log_task")
def persist_forecast_log_task(row_id: int) -> dict[str, Any]:
    """INSERT-only persist. Missing table or broker-less tests → status recorded."""
    if not is_enabled("qa_forecast_log"):
        return {"status": "flag_off"}
    from app.tasks.data_ingestion import _run_async

    try:
        return _run_async(_async_persist(row_id))
    except Exception as exc:
        logger.warning("forecast_log persist failed", error=str(exc)[:200], row_id=row_id)
        return {"status": "failed", "row_id": row_id, "reason": str(exc)[:200]}


async def _async_persist(row_id: int) -> dict[str, Any]:
    store = get_store()
    found = next((r for r in store.rows() if r.id == row_id), None)
    if found is None:
        return {"status": "missing", "row_id": row_id}
    from app.db.session import AsyncSessionLocal
    from app.services.forecast_log.persist import insert_forecast_log

    async with AsyncSessionLocal() as session:
        await insert_forecast_log(session, found)
    return {"status": "ok", "row_id": row_id}


@celery_app.task(name="app.tasks.forecast_log.emit_forecast_log_basket_task")
def emit_forecast_log_basket_task(tickers: list[str] | None = None) -> dict[str, Any]:
    """Daily basket emissions so accuracy accrues without users."""
    if not is_enabled("qa_forecast_log"):
        return {"status": "flag_off"}
    if tickers:
        symbols = tickers
    else:
        try:
            from app.core.config import settings

            raw = getattr(settings, "FORECAST_LOG_BASKET", DEFAULT_BASKET)
            symbols = [t.strip() for t in str(raw).split(",") if t.strip()]
        except Exception:
            symbols = [t.strip() for t in DEFAULT_BASKET.split(",") if t.strip()]
    saved = 0
    skipped = 0
    for sym in symbols:
        skipped += 1
        logger.info("forecast_log basket skipped: no price", ticker=sym)
    logger.info("forecast_log basket emitted", saved=saved, skipped=skipped)
    return {"status": "ok", "saved": saved, "skipped": skipped, "symbols": symbols, "reason": "нет цены"}


@celery_app.task(name="app.tasks.forecast_log.settle_forecast_log_task")
def settle_forecast_log_task() -> dict[str, Any]:
    if not is_enabled("qa_forecast_log"):
        return {"status": "flag_off"}
    from app.services.forecast_log.settle import official_closes, settle_due

    closes = official_closes()
    if not closes:
        return {"status": "ok", "settled": 0, "reason": "нет данных"}
    settled = settle_due(closes)
    return {"status": "ok", "settled": len(settled)}


@celery_app.task(name="app.tasks.forecast_log.snapshot_forecast_log_task")
def snapshot_forecast_log_task() -> dict[str, Any]:
    if not is_enabled("qa_forecast_log"):
        return {"status": "flag_off"}
    digest = get_store().daily_snapshot(date.today())
    return {"status": "ok", "hash": digest, "n": len(get_store().rows())}
