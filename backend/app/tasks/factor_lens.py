"""Daily factor return rebuild."""
from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.factor_lens.rebuild_factor_returns")
def rebuild_factor_returns() -> dict:
    from app.services.factor_lens.ingest import rebuild_daily

    return rebuild_daily()
