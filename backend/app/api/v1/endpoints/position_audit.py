"""Position audit API endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db, get_user_db, require_admin
from app.core.logging import get_logger
from app.db.models import PositionAudit
from app.services.audit.repository import (
    AUDIT_BATCH_SIZE,
    audit_ready,
    count_expiration_closes_since_last_audit,
    has_running_audit,
    try_enqueue_position_audit,
)
from app.services.portfolio.expiration_close import close_expired_for_user
from app.services.portfolio.user_scope import get_user_by_email
from app.tasks.position_audit import run_position_audit_task

router = APIRouter(prefix="/portfolio/position-audit", tags=["position-audit"])
logger = get_logger(__name__)


@router.get("/status")
async def get_audit_status(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    """Count closed trades since last audit; message for UI."""
    user = await get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await close_expired_for_user(db, user.id)
    count, _ = await count_expiration_closes_since_last_audit(db, user.id)
    running = await has_running_audit(db, user.id)

    if audit_ready(count) and not running:
        audit = await try_enqueue_position_audit(db, user.id)
        if audit is not None:
            await db.commit()
            run_position_audit_task.delay(audit.id)
            running = True

    result = await db.execute(
        select(PositionAudit)
        .where(PositionAudit.user_id == user.id, PositionAudit.status == "complete")
        .order_by(desc(PositionAudit.completed_at))
        .limit(1)
    )
    last_audit = result.scalar_one_or_none()

    ready = audit_ready(count) and not running
    message_ru = (
        "Нет новых закрытых сделок — аудит ждёт следующую"
        if count < AUDIT_BATCH_SIZE
        else f"Новых закрытий: {count}. Аудит идёт после каждой закрытой сделки."
    )

    return {
        "expiration_close_count": count,
        "required_count": AUDIT_BATCH_SIZE,
        "ready_to_trigger": ready,
        "audit_running": running,
        "message_ru": message_ru,
        "last_audit_id": last_audit.id if last_audit else None,
        "last_audit_completed_at": (
            last_audit.completed_at.isoformat() if last_audit and last_audit.completed_at else None
        ),
    }


@router.post("/trigger")
async def trigger_audit(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    """Enqueue async audit if there is at least one new closed trade."""
    user = await get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await close_expired_for_user(db, user.id)
    count, _ = await count_expiration_closes_since_last_audit(db, user.id)
    if not audit_ready(count):
        return {
            "status": "insufficient",
            "expiration_close_count": count,
            "required_count": AUDIT_BATCH_SIZE,
            "message_ru": "Нет новых закрытых сделок — аудит ждать нечего",
        }

    if await has_running_audit(db, user.id):
        return {"status": "already_running", "expiration_close_count": count}

    audit = await try_enqueue_position_audit(db, user.id)
    if audit is None:
        return {"status": "already_running", "expiration_close_count": count}

    await db.commit()
    run_position_audit_task.delay(audit.id)
    logger.info("position_audit_triggered", audit_id=audit.id, user_id=user.id)
    return {
        "status": "queued",
        "audit_id": audit.id,
        "expiration_close_count": count,
        "required_count": AUDIT_BATCH_SIZE,
    }


@router.get("/summary")
async def get_user_audit_summary(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    """Simple personal summary from the latest completed audit."""
    user = await get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    result = await db.execute(
        select(PositionAudit)
        .where(PositionAudit.user_id == user.id, PositionAudit.status == "complete")
        .order_by(desc(PositionAudit.completed_at))
        .limit(1)
    )
    audit = result.scalar_one_or_none()
    if audit is None:
        return {"status": "no_audit", "message_ru": "Аудит ещё не проводился"}

    return {
        "status": "complete",
        "audit_id": audit.id,
        "completed_at": audit.completed_at.isoformat() if audit.completed_at else None,
        **audit.user_summary,
    }


@router.get("/report/{audit_id}")
async def get_audit_report(
    audit_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Admin-only: download HTML tear sheet."""
    result = await db.execute(select(PositionAudit).where(PositionAudit.id == audit_id))
    audit = result.scalar_one_or_none()
    if audit is None or not audit.report_path:
        raise HTTPException(status_code=404, detail="Отчёт не найден")

    path = Path(audit.report_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл отчёта недоступен")
    return FileResponse(path, media_type="text/html", filename=path.name)


@router.get("/report/{audit_id}/metrics")
async def get_audit_admin_metrics(
    audit_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Admin-only: full audit metrics JSON."""
    result = await db.execute(select(PositionAudit).where(PositionAudit.id == audit_id))
    audit = result.scalar_one_or_none()
    if audit is None:
        raise HTTPException(status_code=404, detail="Аудит не найден")
    return {
        "audit_id": audit.id,
        "status": audit.status,
        "trade_count": audit.trade_count,
        "admin_metrics": audit.admin_metrics,
    }
