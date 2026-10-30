"""API: Admissions CRM (Prompt 57)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import get_client_ip
from app.core.deps import get_current_user_email, get_db
from app.db.models import User
from app.domain.admissions import (
    AdmissionApplicationCreate,
    AdmissionCaseCreate,
    AdmissionCaseRead,
    AdmissionStatus,
    AssignOwnerBody,
    CallNoteCreate,
    ChangeStatusBody,
    InviteAccessBody,
    RejectBody,
)
from app.core.rbac_deps import get_user_and_role
from app.core.config import settings
from app.domain.device_identity import ip_range_key
from app.domain.rbac import has_permission
from app.services.application.turnstile import verify_turnstile
from app.services.admissions.service import admissions_service
from app.services.signup_abuse.guard import score_signup_abuse_async
from app.schemas.schemas import PaginatedResponse
from app.utils.cache import rate_limit_check

router = APIRouter(prefix="/admissions", tags=["admissions"])


async def _require_crm(db: AsyncSession, email: str) -> User:
    user, role = await get_user_and_role(db, email)
    if not has_permission(role, "crm.read"):
        raise HTTPException(403, "Нет доступа к заявкам")
    return user


async def _require_crm_write(db: AsyncSession, email: str) -> User:
    user, role = await get_user_and_role(db, email)
    if not has_permission(role, "crm.write"):
        raise HTTPException(403, "Нет прав изменять заявки")
    return user


@router.post("/apply", response_model=AdmissionCaseRead, status_code=201)
async def apply_public(
    body: AdmissionApplicationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Public admission lead — no login required. Prefer /auth/register so the user picks a password."""
    from app.services.legal.gates import CLOSED_REASON, registration_open

    if not registration_open():
        raise HTTPException(403, f"Регистрация {CLOSED_REASON}.")
    ip = get_client_ip(request) or "0.0.0.0"
    if settings.TURNSTILE_SECRET_KEY:
        if not await verify_turnstile(body.turnstile_token or "", ip):
            raise HTTPException(400, "Проверка безопасности не пройдена. Обновите страницу.")
    allowed, _remaining = await rate_limit_check(
        f"admission_apply:{ip}", 10, 3600, fail_closed=True
    )
    if not allowed:
        raise HTTPException(429, "Слишком много заявок с этого адреса. Повторите позже.")

    contact_email = body.contact_email.strip().lower()
    allowed_email, _ = await rate_limit_check(
        f"admission_apply_email:{contact_email}", 3, 86400, fail_closed=True
    )
    if not allowed_email:
        raise HTTPException(429, "Заявка с этого email уже отправлялась недавно. Дождитесь ответа команды.")

    abuse = await score_signup_abuse_async(
        db,
        email=contact_email,
        ip_range=ip_range_key(ip),
        timezone_mismatch=False,
        phone=body.contact_phone,
    )
    if abuse.decision_hint == "block":
        raise HTTPException(403, "Заявка отклонена системой защиты от злоупотреблений.")

    apply_extra: dict = {"apply_ip": ip}
    if body.fingerprint:
        apply_extra["apply_fingerprint"] = body.fingerprint[:128]

    case = await admissions_service.create_lead(
        db,
        AdmissionCaseCreate(
            contact_email=contact_email,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            source="web_application",
            jurisdiction=body.jurisdiction,
            capital_range=body.capital_range,
            experience_level=body.experience_level,
            strategy_interest=body.strategy_interest,
            notes=body.notes,
        ),
        actor_user_id=None,
    )
    case.extra = {**(getattr(case, "extra", None) or {}), **apply_extra}
    await db.commit()
    await db.refresh(case)
    return await admissions_service.to_read_enriched(db, case)


@router.post("/invite")
async def invite_access(
    body: InviteAccessBody,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    """Operator: create a login and mark the admission case approved."""
    user = await _require_crm_write(db, email)
    case, plaintext, existing = await admissions_service.invite_and_approve(
        db,
        email=body.contact_email,
        contact_name=body.contact_name,
        actor_user_id=user.id,
    )
    await db.commit()
    await db.refresh(case)
    return {
        "ok": True,
        "existing_user": existing,
        "email": case.contact_email,
        "case_id": case.id,
        "temporary_password": None,
        "password_delivery": "email" if plaintext else None,
        "must_change_password": bool(plaintext),
    }


@router.get("")
async def list_admissions(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    from app.domain.admissions import DISPLAY_BUCKETS, display_bucket_for_status

    await _require_crm(db, email)
    cases = await admissions_service.list_cases(db)
    by_status: dict[str, list[dict]] = {s.value: [] for s in AdmissionStatus}
    buckets: dict[str, list[dict]] = {key: [] for key in DISPLAY_BUCKETS}
    for c in cases:
        enriched = await admissions_service.to_read_enriched(db, c)
        payload = enriched.model_dump(mode="json")
        by_status.setdefault(c.status, []).append(payload)
        buckets.setdefault(display_bucket_for_status(c.status), []).append(payload)
    return {"columns": by_status, "buckets": buckets, "total": len(cases)}


@router.get("/list", response_model=PaginatedResponse)
async def list_admissions_paginated(
    status: str | None = Query(None, description="Filter by admission status"),
    bucket: str | None = Query(None, description="trial | paying | full | blocked"),
    sort: str = Query("created_at_desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    await _require_crm(db, email)
    cases, total = await admissions_service.list_cases_paginated(
        db,
        status=status,
        bucket=bucket,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    items = []
    for case in cases:
        enriched = await admissions_service.to_read_enriched(db, case)
        items.append(enriched.model_dump(mode="json"))
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.post("/seed-demo")
async def seed_demo_admissions(
    count: int = Query(30, ge=1, le=100),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    if not settings.DEBUG:
        raise HTTPException(403, "Демо-данные недоступны")
    await _require_crm_write(db, email)
    created = await admissions_service.seed_demo_cases(db, count=count)
    await db.commit()
    return {"created": created, "requested": count}


@router.post("", response_model=AdmissionCaseRead)
async def create_lead(
    body: AdmissionCaseCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_crm_write(db, email)
    case = await admissions_service.create_lead(db, body, actor_user_id=user.id)
    await db.commit()
    await db.refresh(case)
    return await admissions_service.to_read_enriched(db, case)


@router.get("/export.csv")
async def export_csv(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    await _require_crm(db, email)
    cases = await admissions_service.list_cases(db)
    csv_text = admissions_service.export_bitrix_csv(cases)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=admissions_bitrix.csv"},
    )


@router.get("/{case_id}", response_model=AdmissionCaseRead)
async def get_case(
    case_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    await _require_crm(db, email)
    case = await admissions_service.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Не найдено")
    return admissions_service.to_read(case)


@router.post("/{case_id}/start-trial")
async def start_trial(
    case_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_crm_write(db, email)
    try:
        case, eligibility = await admissions_service.start_trial(
            db, case_id, actor_user_id=user.id
        )
    except Exception as exc:
        raise HTTPException(400, "Не удалось выполнить действие. Проверьте данные.") from exc
    await db.commit()
    return {"case": admissions_service.to_read(case), "trial_eligibility": eligibility}


@router.post("/{case_id}/assign-owner", response_model=AdmissionCaseRead)
async def assign_owner(
    case_id: str,
    body: AssignOwnerBody,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_crm_write(db, email)
    case = await admissions_service.assign_owner(
        db, case_id, body.owner_user_id, actor_user_id=user.id
    )
    await db.commit()
    return admissions_service.to_read(case)


@router.post("/{case_id}/notes", response_model=AdmissionCaseRead)
async def add_note(
    case_id: str,
    body: CallNoteCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_crm(db, email)
    case = await admissions_service.add_call_note(db, case_id, body.note, actor_user_id=user.id)
    await db.commit()
    return admissions_service.to_read(case)


@router.post("/{case_id}/approve", response_model=AdmissionCaseRead)
async def approve(
    case_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_crm_write(db, email)
    try:
        case = await admissions_service.approve_account(db, case_id, actor_user_id=user.id)
    except Exception as exc:
        raise HTTPException(400, "Не удалось выполнить действие. Проверьте данные.") from exc
    await db.commit()
    return await admissions_service.to_read_enriched(db, case)


@router.post("/{case_id}/grant-admin", response_model=AdmissionCaseRead)
async def grant_admin(
    case_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_crm_write(db, email)
    try:
        case = await admissions_service.grant_admin(db, case_id, actor_user_id=user.id)
    except Exception as exc:
        raise HTTPException(400, "Не удалось выполнить действие. Проверьте данные.") from exc
    await db.commit()
    return await admissions_service.to_read_enriched(db, case)


@router.post("/{case_id}/revoke-admin", response_model=AdmissionCaseRead)
async def revoke_admin(
    case_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_crm_write(db, email)
    try:
        case = await admissions_service.revoke_admin(db, case_id, actor_user_id=user.id)
    except Exception as exc:
        raise HTTPException(400, "Не удалось выполнить действие. Проверьте данные.") from exc
    await db.commit()
    return await admissions_service.to_read_enriched(db, case)


@router.post("/{case_id}/suspend", response_model=AdmissionCaseRead)
async def suspend_full_access(
    case_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_crm_write(db, email)
    try:
        case = await admissions_service.suspend_full_access(db, case_id, actor_user_id=user.id)
    except Exception as exc:
        raise HTTPException(400, "Не удалось выполнить действие. Проверьте данные.") from exc
    await db.commit()
    return await admissions_service.to_read_enriched(db, case)


@router.post("/{case_id}/reject", response_model=AdmissionCaseRead)
async def reject(
    case_id: str,
    body: RejectBody,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_crm_write(db, email)
    try:
        case = await admissions_service.reject_account(
            db, case_id, body.reason, actor_user_id=user.id
        )
    except Exception as exc:
        raise HTTPException(400, "Не удалось выполнить действие. Проверьте данные.") from exc
    await db.commit()
    return admissions_service.to_read(case)


@router.post("/{case_id}/escalate", response_model=AdmissionCaseRead)
async def escalate(
    case_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_crm_write(db, email)
    case = await admissions_service.escalate_case(db, case_id, actor_user_id=user.id)
    await db.commit()
    return admissions_service.to_read(case)


@router.post("/{case_id}/status", response_model=AdmissionCaseRead)
async def change_status(
    case_id: str,
    body: ChangeStatusBody,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user, role = await get_user_and_role(db, email)
    if not has_permission(role, "crm.write"):
        raise HTTPException(403, "Нет прав изменять заявки")
    try:
        case = await admissions_service.change_status(
            db,
            case_id,
            body.status,
            actor_user_id=user.id,
            reason=body.reason,
            admin_override=has_permission(role, "*"),
        )
    except Exception as exc:
        raise HTTPException(400, "Не удалось выполнить действие. Проверьте данные.") from exc
    await db.commit()
    return admissions_service.to_read(case)


@router.get("/{case_id}/bitrix-card", response_class=PlainTextResponse)
async def bitrix_card(
    case_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    await _require_crm(db, email)
    case = await admissions_service.get_case(db, case_id)
    if not case:
        raise HTTPException(404, "Не найдено")
    row = admissions_service.case_to_bitrix_row(case)
    lines = [f"{k}: {v}" for k, v in row.items()]
    return "\n".join(lines)
