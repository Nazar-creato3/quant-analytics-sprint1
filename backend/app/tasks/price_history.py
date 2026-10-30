"""Nightly daily-price history for every held instrument, benchmarks and FX."""
from __future__ import annotations

from typing import Any

from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.price_history.sync_price_history_task")
def sync_price_history_task(force: bool = False, tickers: list[str] | None = None) -> dict[str, Any]:
    from app.services.price_history.sync import sync

    out = run_async(sync(tickers, force=force))
    return {"total": out["total"], "ok": out["ok"], "fx": out["fx"]}
