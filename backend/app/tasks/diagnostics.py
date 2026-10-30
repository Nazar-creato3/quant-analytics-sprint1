"""Scheduled diagnostics (Prompt 89)."""
from __future__ import annotations

from app.tasks.celery_app import celery_app
from app.tasks.async_runner import run_async


@celery_app.task(name="app.tasks.diagnostics.run_diagnostics_task", track_started=True)
def run_diagnostics_task() -> dict:
    """Daily invariant + golden regression checks."""

    async def _run() -> dict:
        from app.services.diagnostics.engine import DiagnosticsEngine
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            try:
                from app.services.macro.client import fetch_and_store_macro_events

                await fetch_and_store_macro_events(session)
            except Exception:
                raise

        engine = DiagnosticsEngine()
        report = await engine.run_and_alert()
        return {
            "ok": report.ok,
            "checks": len(report.findings),
            "failures": [f.check_id for f in report.failures()],
        }

    return run_async(_run())
