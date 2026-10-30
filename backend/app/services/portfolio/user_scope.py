"""Per-user scoping for portfolio data (maneuvers, grid bots, deal intents)."""
from __future__ import annotations

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Maneuver, ManeuverReport, User
from app.domain.deal_intent import DealIntentORM
from app.domain.sleeve import SleeveORM


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


def deal_intents_for_user(user_id: str, *, staff_all: bool = False) -> Select:
    """DealIntents owned by user via sleeve.profile_id.

    Staff with staff_all=True may access any deal intent (review/ops).
    """
    base = select(DealIntentORM).join(SleeveORM, DealIntentORM.sleeve_id == SleeveORM.id)
    if staff_all:
        return base
    return base.where(SleeveORM.profile_id == user_id)


def deal_intent_for_user(
    user_id: str,
    deal_intent_id: str,
    *,
    staff_all: bool = False,
) -> Select:
    """Single deal intent visible to user (404 when out of scope)."""
    return deal_intents_for_user(user_id, staff_all=staff_all).where(
        DealIntentORM.id == deal_intent_id
    )


async def load_deal_intent_for_user(
    db: AsyncSession,
    user_id: str,
    deal_intent_id: str,
    *,
    staff_all: bool = False,
) -> DealIntentORM | None:
    result = await db.execute(
        deal_intent_for_user(user_id, deal_intent_id, staff_all=staff_all)
    )
    return result.scalar_one_or_none()


def reports_for_user(user_id: str) -> Select:
    """Maneuver reports owned by the user (strict — no orphans, no cross-user)."""
    return select(ManeuverReport).where(ManeuverReport.created_by == user_id)


def report_for_user(user_id: str, report_id: str) -> Select:
    """Single report visible to user (404 when out of scope)."""
    return reports_for_user(user_id).where(ManeuverReport.id == report_id)


async def load_report_for_user(
    db: AsyncSession,
    user_id: str,
    report_id: str,
) -> ManeuverReport | None:
    result = await db.execute(report_for_user(user_id, report_id))
    return result.scalar_one_or_none()


def maneuvers_for_user(user_id: str, *, staff_include_orphans: bool = False) -> Select:
    """Maneuvers owned by user via report.created_by.

    Orphan pipeline rows (created_by IS NULL) are excluded from personal portfolio
    views. Pass staff_include_orphans=True only for explicit operator/admin lists.
    """
    base = select(Maneuver).join(ManeuverReport, Maneuver.report_id == ManeuverReport.id)
    if staff_include_orphans:
        return base.where(
            or_(
                ManeuverReport.created_by == user_id,
                ManeuverReport.created_by.is_(None),
            )
        )
    return base.where(ManeuverReport.created_by == user_id)


def orphan_pipeline_maneuvers() -> Select:
    """Admin/ops view of pipeline maneuvers with no report owner."""
    return (
        select(Maneuver)
        .join(ManeuverReport, Maneuver.report_id == ManeuverReport.id)
        .where(ManeuverReport.created_by.is_(None))
    )


def maneuver_for_user(
    user_id: str,
    maneuver_id: str,
    *,
    staff_include_orphans: bool = False,
) -> Select:
    """Single maneuver visible to user (404 when out of scope)."""
    return maneuvers_for_user(
        user_id,
        staff_include_orphans=staff_include_orphans,
    ).where(Maneuver.id == maneuver_id)


async def load_maneuver_for_user(
    db: AsyncSession,
    user_id: str,
    maneuver_id: str,
    *,
    staff_include_orphans: bool = False,
) -> Maneuver | None:
    result = await db.execute(
        maneuver_for_user(
            user_id,
            maneuver_id,
            staff_include_orphans=staff_include_orphans,
        )
    )
    return result.scalar_one_or_none()


def filter_grid_bots_for_user(bots: dict[str, dict], email: str) -> dict[str, dict]:
    """Keep only grid bots created by the given user."""
    owner = email.lower()
    return {
        bot_id: data
        for bot_id, data in bots.items()
        if (data.get("created_by") or "").lower() == owner
    }


def assert_grid_bot_owner(data: dict, email: str) -> None:
    from fastapi import HTTPException, status

    owner = (data.get("created_by") or "").lower()
    if owner and owner != email.lower():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grid bot not found")
