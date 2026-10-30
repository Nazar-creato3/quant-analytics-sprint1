"""Weekly backtest analysis Celery task."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.backtest_analysis.run_weekly_analysis_task")
def run_weekly_analysis_task(days: int = 7) -> dict[str, Any]:
    return run_async(_async_weekly_analysis(days))


async def _async_weekly_analysis(days: int) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import BacktestRun
    from app.db.session import AsyncSessionLocal
    from app.services.backtest_analysis.weekly import build_weekly_report

    async with AsyncSessionLocal() as session:
        report = await build_weekly_report(session, days=days)

        # Persist for /backtest/reports/weekly only — never list as a ticker run (GA16-273).
        history = BacktestRun(
            strategy="weekly_analysis",
            ticker="—",
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc),
            initial_capital=float(report.get("reference_capital") or 0.0),
            status="complete",
            metrics=report,
            trade_log=[],
            equity_curve=report.get("equity_curve_sample", []),
            completed_at=datetime.now(timezone.utc),
        )
        session.add(history)
        await session.commit()
        await session.refresh(history)

        logger.info(
            "Weekly backtest analysis complete",
            report_id=history.id,
            week=report.get("week_label"),
            runs=report.get("run_count"),
        )
        return {"report_id": history.id, "week_label": report.get("week_label"), "status": "complete"}
