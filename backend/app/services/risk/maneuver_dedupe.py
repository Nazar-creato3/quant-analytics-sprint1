"""Skip pipeline inserts that repeat the same ticker + thesis."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Maneuver, ManeuverReport, ManeuverStatus


def maneuver_content_key(
    ticker: str,
    direction: Any,
    confidence: Any,
    rationale: str | None,
) -> str:
    try:
        conf = f"{float(confidence or 0.0):.2f}"
    except (TypeError, ValueError):
        conf = "0.00"
    rat = " ".join((rationale or "").split())[:200]
    return f"{str(ticker).strip().upper()}|{str(direction).strip().lower()}|{conf}|{rat}"


# Ideas the user already acted on: a repeat within the window is not shown again.
_ACTED_STATUSES = [
    ManeuverStatus.APPROVED,
    ManeuverStatus.REJECTED,
    ManeuverStatus.EXECUTING,
    ManeuverStatus.FILLED,
]


async def existing_maneuver_keys(
    session: AsyncSession,
    *,
    user_id: str,
    hours: int = 48,
) -> set[str]:
    """Keys of recent maneuvers the user approved, rejected or executed (skip repeats)."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await session.execute(
        select(
            Maneuver.ticker,
            Maneuver.direction,
            Maneuver.confidence,
            Maneuver.rationale,
        )
        .join(ManeuverReport, Maneuver.report_id == ManeuverReport.id)
        .where(ManeuverReport.created_by == user_id)
        .where(Maneuver.created_at >= since)
        .where(Maneuver.status.in_(_ACTED_STATUSES))
    )
    keys: set[str] = set()
    for ticker, direction, confidence, rationale in rows.all():
        keys.add(maneuver_content_key(ticker, direction, confidence, rationale))
    return keys


async def supersede_pending_duplicates(
    session: AsyncSession,
    *,
    user_id: str,
    new_keys: set[str],
    hours: int = 48,
) -> int:
    """Mark older still-pending copies of the new report's ideas as withdrawn.

    Previously a repeated idea was dropped from the new report, so re-running the
    selection on unchanged data (night, weekend) produced an almost empty report.
    Now the newest report is always complete and the stale pending copy is withdrawn,
    so the same idea is never pending twice.
    """
    if not new_keys:
        return 0
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await session.execute(
        select(Maneuver)
        .join(ManeuverReport, Maneuver.report_id == ManeuverReport.id)
        .where(ManeuverReport.created_by == user_id)
        .where(Maneuver.created_at >= since)
        .where(Maneuver.status == ManeuverStatus.PENDING)
    )
    n = 0
    for m in rows.scalars().all():
        if maneuver_content_key(m.ticker, m.direction, m.confidence, m.rationale) in new_keys:
            m.status = ManeuverStatus.INVALIDATED
            n += 1
    return n
