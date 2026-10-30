"""Celery tasks for scheduled StressHarness runs (Prompt 27)."""
from __future__ import annotations

from sqlalchemy import select

from app.db.models import User
from app.db.session import AsyncSessionLocal
from app.services.stress_harness import StressHarness
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


def public_daily_stress_row(report) -> dict[str, object]:
    return {
        "max_loss_usd": report.max_loss_usd,
        "positions_to_review": len(report.positions_to_review),
    }


@celery_app.task(name="app.tasks.stress_harness.run_daily_stress_task")
def run_daily_stress_task() -> dict[str, object]:
    """Run full stress suite once per day for every profile with open positions."""

    async def _run() -> dict[str, object]:
        harness = StressHarness()
        reports: list[dict[str, object]] = []
        skipped = 0

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User.id))
            profile_ids = [row[0] for row in result.all()]

            for profile_id in profile_ids:
                context = await harness.loader.load_profile_portfolio(db, profile_id)
                if not context.portfolio.positions:
                    skipped += 1
                    continue
                report = harness.run_all_scenarios(context)
                reports.append(public_daily_stress_row(report))

        return {
            "profiles_tested": len(reports),
            "profiles_skipped": skipped,
            "reports": reports,
        }

    return run_async(_run())
