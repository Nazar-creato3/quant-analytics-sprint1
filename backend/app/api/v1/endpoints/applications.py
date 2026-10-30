"""Application flow API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_admin
from app.domain.application_flow import (
    ApplicationRead,
    ApplicationRequestOtpIn,
    ApplicationSubmitIn,
)
from app.services.application.service import application_service
from app.services.crm.sync import schedule_application_crm_sync

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("/request-otp")
async def request_otp(_body: ApplicationRequestOtpIn):
    raise HTTPException(
        status.HTTP_410_GONE,
        "Публичные заявки отключены. Доступ выдаёт администратор.",
    )


@router.post("/submit", response_model=ApplicationRead, status_code=201)
async def submit_application(_body: ApplicationSubmitIn):
    raise HTTPException(
        status.HTTP_410_GONE,
        "Публичные заявки отключены. Доступ выдаёт администратор.",
    )


@router.get("/verify-email")
async def verify_email(
    request: Request,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    from app.core.client_ip import get_client_ip
    from app.utils.cache import rate_limit_check

    ip = get_client_ip(request) or "0.0.0.0"
    allowed, _ = await rate_limit_check(f"app_verify_email:{ip}", 20, 3600, fail_closed=True)
    if not allowed:
        raise HTTPException(429, "Слишком много попыток")
    app = await application_service.verify_email(db, token)
    if not app:
        raise HTTPException(404, "Ссылка недействительна или устарела")
    await db.commit()
    schedule_application_crm_sync(app.id, "email_verified")
    return {"ok": True, "status": app.status, "application_id": app.id}


@router.post("/{application_id}/approve")
async def approve_application(
    application_id: str,
    _: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        app, _password = await application_service.approve(db, application_id)
    except LookupError as exc:
        raise HTTPException(404, "Заявка не найдена") from exc
    except ValueError as exc:
        raise HTTPException(400, "Сейчас заявку одобрить нельзя.") from exc
    await db.commit()
    schedule_application_crm_sync(app.id, "approved")
    return {"ok": True, "application_id": app.id, "user_id": app.user_id}


@router.post("/{application_id}/reject")
async def reject_application(
    application_id: str,
    reason: str = Query(min_length=3),
    _: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        app = await application_service.reject(db, application_id, reason)
    except LookupError as exc:
        raise HTTPException(404, "Заявка не найдена") from exc
    await db.commit()
    schedule_application_crm_sync(app.id, "rejected")
    return {"ok": True, "application_id": app.id, "status": app.status}
