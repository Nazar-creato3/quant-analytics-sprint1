"""Full position audit pipeline orchestrator."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import PositionAudit
from app.services.alerts.telegram import send_telegram_message
from app.services.audit.core_stats import compute_core_stats
from app.services.audit.execution_quality import compute_execution_quality
from app.services.audit.expiration_analysis import compute_expiration_analysis
from app.services.audit.factor_attribution import compute_factor_attribution
from app.services.audit.pattern_analysis import compute_pattern_analysis
from app.services.audit.repository import AUDIT_BATCH_SIZE, fetch_audit_trades
from app.services.audit.r_multiple import compute_r_multiple_stats
from app.services.audit.streak_analysis import compute_monte_carlo_bust, compute_streak_analysis
from app.services.audit.tear_sheet import generate_tear_sheet
from app.services.audit.user_summary import build_user_summary, resolve_most_common_maneuver

logger = get_logger(__name__)


async def run_position_audit(db: AsyncSession, audit_id: str) -> dict[str, Any]:
    """Execute the full audit pipeline for a pending audit row."""
    from sqlalchemy import select

    result = await db.execute(select(PositionAudit).where(PositionAudit.id == audit_id))
    audit = result.scalar_one_or_none()
    if audit is None:
        raise ValueError(f"Audit {audit_id} not found")

    audit.status = "running"
    audit.started_at = datetime.now(timezone.utc)
    await db.commit()

    try:
        trades = await fetch_audit_trades(db, audit.user_id, limit=AUDIT_BATCH_SIZE)
        if len(trades) < AUDIT_BATCH_SIZE:
            raise ValueError(
                f"Insufficient closed trades for audit: {len(trades)}/{AUDIT_BATCH_SIZE}"
            )

        admin_metrics: dict[str, Any] = {
            "core_stats": compute_core_stats(trades),
            "r_multiple": compute_r_multiple_stats(trades),
            "factor_attribution": compute_factor_attribution(trades),
            "pattern_analysis": compute_pattern_analysis(trades),
            "expiration_analysis": compute_expiration_analysis(trades),
            "execution_quality": compute_execution_quality(trades),
            "streak_analysis": compute_streak_analysis(trades),
            "monte_carlo": compute_monte_carlo_bust(trades),
        }

        most_common = await resolve_most_common_maneuver(db, audit.user_id)
        user_summary = build_user_summary(trades, most_common_maneuver=most_common)

        report_path = generate_tear_sheet(trades, admin_metrics, audit_id=audit_id)

        audit.admin_metrics = admin_metrics
        audit.user_summary = user_summary
        audit.report_path = str(report_path)
        audit.trade_count = len(trades)
        audit.status = "complete"
        audit.completed_at = datetime.now(timezone.utc)
        await db.commit()

        await _notify_admin(audit_id, len(trades), report_path)
        logger.info("position_audit_complete", audit_id=audit_id, trades=len(trades))
        return {"audit_id": audit_id, "status": "complete", "trade_count": len(trades)}

    except Exception as exc:
        audit.status = "failed"
        audit.error_message = str(exc)
        audit.completed_at = datetime.now(timezone.utc)
        await db.commit()
        logger.exception("position_audit_failed", audit_id=audit_id, error=str(exc))
        raise


async def _notify_admin(audit_id: str, trade_count: int, report_path: Any) -> None:
    chat_id = (settings.TELEGRAM_CHAT_ID or "").strip()
    if not chat_id:
        return
    base_url = getattr(settings, "PUBLIC_BASE_URL", None) or "https://quantanalyticsclub.ru"
    text = (
        f"📊 Position Audit готов\n"
        f"ID: {audit_id}\n"
        f"Сделок: {trade_count}\n"
        f"Отчёт: {base_url}/api/v1/portfolio/position-audit/report/{audit_id}"
    )
    await send_telegram_message(chat_id, text, settings=settings)
