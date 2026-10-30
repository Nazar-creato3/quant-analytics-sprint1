"""Enqueue market-analysis pipeline runs on the dedicated Celery queue."""
from __future__ import annotations

from typing import Any


_RUN_EXPIRES_SEC = 900


def dispatch_pipeline_task(
    *,
    run_id: str,
    watchlist: list[str],
    portfolio_size: float,
    confidence_threshold: float | None = None,
    triggered_by: str = "manual",
    skip_auto_execute: bool = True,
    owner_user_id: str | None = None,
) -> str:
    """Return Celery task id for a pipeline run (queue=pipeline, high priority)."""
    from app.tasks.pipeline import run_pipeline_task

    kwargs: dict[str, Any] = {
        "confidence_threshold": confidence_threshold,
        "triggered_by": triggered_by,
        "skip_auto_execute": skip_auto_execute,
        "owner_user_id": owner_user_id,
    }
    task = run_pipeline_task.apply_async(
        args=[run_id, watchlist, portfolio_size],
        kwargs=kwargs,
        queue="pipeline",
        priority=9,
        # acks_late redelivers an unfinished run after every worker restart (deploy); an old
        # run then occupies a worker for minutes while the user's new click waits behind it.
        # A run that has not started within this window is dropped by the worker.
        expires=_RUN_EXPIRES_SEC,
    )
    return task.id
