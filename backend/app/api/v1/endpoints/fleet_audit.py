"""Admin fleet book — all accounts. Never attached to user pipeline."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_admin
from app.core.logging import get_logger
from app.services.audit.fleet import load_latest_fleet_snapshot, refresh_fleet_snapshot

router = APIRouter(prefix="/admin/fleet-audit", tags=["admin-fleet-audit"])
logger = get_logger(__name__)


def _public_snapshot(payload: dict[str, Any], *, limit: int) -> dict[str, Any]:
    accounts = list(payload.get("accounts") or [])
    clipped = []
    for raw in accounts[: max(0, limit)]:
        row = dict(raw)
        row.pop("user_id", None)
        clipped.append(row)
    return {
        **payload,
        "accounts": clipped,
        "accounts_truncated": max(0, len(accounts) - len(clipped)),
        "feeds_maneuver_factory": False,
        "venue_api_called": False,
    }


@router.get("")
async def get_fleet_audit(
    limit: int = Query(80, ge=1, le=400),
    refresh: bool = Query(False),
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    snap = None if refresh else await load_latest_fleet_snapshot()
    if snap is None:
        snap = await refresh_fleet_snapshot(db)
        logger.info("fleet_audit_built_on_read", admin=_admin.get("sub"))
    try:
        from app.services.portfolio.user_scope import get_user_by_email
        from app.utils.audit import AuditAction, audit

        actor = await get_user_by_email(db, str(_admin.get("sub") or ""))
        if actor:
            await audit.log(
                db,
                action=AuditAction.FLEET_AUDIT_VIEW,
                user_id=actor.id,
                details={"refresh": refresh, "limit": limit},
            )
    except Exception:
        raise
    return _public_snapshot(snap, limit=limit)


@router.post("/refresh")
async def post_fleet_audit_refresh(
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    snap = await refresh_fleet_snapshot(db)
    logger.info("fleet_audit_manual_refresh", admin=_admin.get("sub"), users=snap.get("user_count"))
    return _public_snapshot(snap, limit=80)
