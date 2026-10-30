"""Execution Celery tasks."""
from __future__ import annotations
import asyncio
from app.tasks.celery_app import celery_app
from app.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.execution.execute_maneuver_task",
    max_retries=3,
    default_retry_delay=10,
)
def execute_maneuver_task(self, maneuver_id: str) -> dict:
    """Execute a single approved maneuver via the broker adapter."""
    from app.services.execution.adapter import execute_maneuver
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(execute_maneuver(maneuver_id))
        loop.close()
        return {"maneuver_id": maneuver_id, "status": "executed"}
    except Exception as exc:
        logger.error("Execution task failed", maneuver_id=maneuver_id, error=str(exc))
        self.retry(exc=exc)


@celery_app.task(name="app.tasks.execution.nightly_paper_live_parity_task")
def nightly_paper_live_parity_task(fills: list | None = None) -> dict:
    """Compare paper vs live fill quality from the own tape. Empty → skip."""
    from app.services.execution.fill_tape import load_fills
    from app.services.execution.parity import nightly_parity

    report = nightly_parity(list(fills if fills is not None else load_fills()))
    logger.info(
        "paper_live_parity",
        ok=report.ok,
        drift_bps=report.drift_bps,
        reasons=list(report.reasons),
    )
    return {
        "ok": report.ok,
        "drift_bps": report.drift_bps,
        "paper_is_bps": report.paper_is_bps,
        "live_is_bps": report.live_is_bps,
        "reasons": list(report.reasons),
    }


@celery_app.task(name="app.tasks.execution.nightly_platform_task")
def nightly_platform_task() -> dict:
    """Client pack + freshness/drift snapshot after the book realizes."""
    from app.services.platform_desk.nightly import run_nightly_platform

    out = run_nightly_platform()
    logger.info(
        "platform_nightly",
        holdings=(out.get("report") or {}).get("holdings_n"),
        freshness_ok=(out.get("monitor") or {}).get("freshness_ok"),
    )
    return {
        "holdings_n": (out.get("report") or {}).get("holdings_n"),
        "freshness_ok": (out.get("monitor") or {}).get("freshness_ok"),
        "tear_n": ((out.get("report") or {}).get("tear") or {}).get("n"),
    }


@celery_app.task(name="app.tasks.execution.nightly_ops_dr_task")
def nightly_ops_dr_task() -> dict:
    """Seal operator floor + copy last-good digest/features. No invented capital."""
    from app.core.config import settings
    from app.services.ops_desk.live_hooks import run_nightly_dr

    raw = getattr(settings, "DEFAULT_PORTFOLIO_SIZE", None)
    try:
        cap = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        cap = None
    if cap is None or cap <= 0:
        logger.info("ops_nightly_dr skipped: no deploy cap")
        return {"ok": False, "reason": "нет данных"}
    out = run_nightly_dr(settings_cap=cap, account_total=None)
    logger.info(
        "ops_nightly_dr",
        deploy_cap=(out.get("seal") or {}).get("deploy_cap"),
        copied=(out.get("backup") or {}).get("copied"),
    )
    return out


@celery_app.task(name="app.tasks.execution.refresh_tbank_orders_task")
def refresh_tbank_orders_task() -> dict:
    """Settle T-Bank orders that were still resting at submission time."""
    from app.db.session import AsyncSessionLocal
    from app.services.broker.tbank_order_refresh import refresh_open_tbank_orders

    async def _run() -> dict:
        async with AsyncSessionLocal() as session:
            return await refresh_open_tbank_orders(session)

    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(_run())
    finally:
        loop.close()
    if out.get("checked"):
        logger.info("tbank_orders_refreshed", **out)
    return out
