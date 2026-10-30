"""Celery entry for PDN retention (no live deletes without wired stores)."""
from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.pdn_retention.run_pdn_retention")
def run_pdn_retention() -> dict:
    from app.services.pdn_retention.job import run_retention_job

    return run_retention_job()
