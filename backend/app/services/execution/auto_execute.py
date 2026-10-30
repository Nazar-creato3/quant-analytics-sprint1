"""
Auto-approve and execute tradeable maneuvers in paper mode after pipeline run.

Paper trading is designed for a hands-off loop: market analysis → maneuvers →
instant paper fills without manual operator approval.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus, StrategyType
from app.db.session import AsyncSessionLocal
from app.services.risk.position_limits import apply_decision_to_maneuver, evaluate_position_limits

logger = get_logger(__name__)

_SYSTEM_EMAIL = "pipeline@system"


def paper_auto_execute_enabled() -> bool:
    return (
        settings.PAPER_TRADING_ENABLED
        and settings.PAPER_AUTO_EXECUTE
        and not settings.live_trading_unlocked
    )


async def auto_execute_paper_maneuvers(maneuver_ids: list[str]) -> dict[str, Any]:
    """
    Approve and execute tradeable maneuvers sequentially in paper mode.

    Runs inline (not via Celery dispatch) so position-limit checks see each
    fill before the next maneuver is sized.
    """
    if not paper_auto_execute_enabled():
        return {
            "enabled": False,
            "dispatched": 0,
            "filled": 0,
            "rejected": 0,
            "skipped": len(maneuver_ids),
        }
    from app.services.order_machine.service import automatic_blocked

    if automatic_blocked(None):
        return {
            "enabled": True,
            "dispatched": 0,
            "filled": 0,
            "rejected": len(maneuver_ids),
            "skipped": 0,
            "reason": "halt",
        }

    from app.services.execution.adapter import execute_maneuver

    dispatched: list[str] = []
    filled: list[str] = []
    rejected: list[dict[str, str]] = []
    skipped = 0

    async with AsyncSessionLocal() as session:
        for maneuver_id in maneuver_ids:
            result = await session.execute(select(Maneuver).where(Maneuver.id == maneuver_id))
            maneuver = result.scalar_one_or_none()
            if not maneuver:
                skipped += 1
                continue

            if maneuver.strategy_type == StrategyType.NO_TRADE:
                skipped += 1
                continue

            if maneuver.status != ManeuverStatus.PENDING:
                skipped += 1
                continue

            decision = await evaluate_position_limits(session, maneuver, _SYSTEM_EMAIL)
            if not decision.allowed:
                rejected.append({"id": maneuver_id, "reason": decision.reason})
                logger.info(
                    "Auto-execute rejected by risk limits",
                    maneuver_id=maneuver_id,
                    reason=decision.reason,
                )
                continue

            if decision.scaled:
                apply_decision_to_maneuver(maneuver, decision)

            maneuver.status = ManeuverStatus.APPROVED
            maneuver.approved_at = datetime.now(timezone.utc)
            await session.commit()
            dispatched.append(maneuver_id)

            try:
                await execute_maneuver(maneuver_id)
                filled.append(maneuver_id)
                logger.info("Paper auto-execute filled", maneuver_id=maneuver_id, ticker=maneuver.ticker)
            except Exception as exc:
                logger.error(
                    "Paper auto-execute failed",
                    maneuver_id=maneuver_id,
                    error=str(exc),
                    exc_info=True,
                )

    return {
        "enabled": True,
        "dispatched": len(dispatched),
        "filled": len(filled),
        "rejected": len(rejected),
        "skipped": skipped,
        "filled_ids": filled,
        "rejected_details": rejected,
    }
