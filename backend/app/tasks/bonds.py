from __future__ import annotations

from app.services.bonds.ingest import load_fixture_universe
from app.services.bonds.service import ensure_fixtures
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.bonds.refresh_bond_reference_task")
def refresh_bond_reference_task() -> dict:
    """A fixture load is not a live refresh."""
    ensure_fixtures()
    return {"ok": False, "reason": "нет данных", "refreshed": 0}


def load_tracked_universe(payload: dict) -> None:
    load_fixture_universe(payload)
