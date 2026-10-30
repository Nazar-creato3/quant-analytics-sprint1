"""Background retention sweep (in-process; Celery entry optional)."""
from __future__ import annotations

from datetime import datetime

from app.services.pdn_retention.policy import plan_purge


def collect_records() -> list[dict]:
    from app.services.waitlist.service import retention_records

    return retention_records()


def run_retention_job(
    records: list[dict] | None = None,
    *,
    now: datetime | None = None,
    launch_at: datetime | None = None,
    apply: bool = True,
) -> dict:
    rows = collect_records() if records is None else records
    purge_ids = plan_purge(rows, now=now, launch_at=launch_at)
    purged = 0
    if apply and purge_ids:
        from app.services.waitlist.service import purge_by_ids

        purged = purge_by_ids(purge_ids)
    else:
        purged = len(purge_ids)
    return {
        "status": "ok",
        "scanned": len(rows),
        "purge_ids": purge_ids,
        "purged": purged,
    }
