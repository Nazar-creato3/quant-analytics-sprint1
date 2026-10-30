"""Subject export. The body must not add an address."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.services.legal import acceptance
from app.services.qa.session_user import require_session_user_id
from app.services.subject_rights.service import delete_account, export_account
from app.utils.audit import AuditAction, audit

router = APIRouter(prefix="/subject-rights", tags=["subject-rights"])
_MISSING = "нет данных"


def _client(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None, request.headers.get("user-agent"))


def get_subject_export(user_id: str) -> dict:
    if "@" in user_id:
        return {"status": "rejected", "reason": _MISSING}
    payload = export_account(user_id)
    payload.pop("email", None)
    payload.pop("name", None)
    return payload


def post_subject_delete(body: dict, session_id: str = "") -> dict:
    if any(key in body for key in ("email", "name", "token")):
        return {"status": "rejected", "reason": _MISSING}
    requested = body.get("user_id")
    if requested is not None and requested != session_id:
        raise HTTPException(status_code=403, detail=_MISSING)
    if "@" in session_id:
        return {"status": "rejected", "reason": _MISSING}
    return delete_account(session_id)


@router.get("/export")
async def route_subject_export(
    request: Request,
    user_id: str = Depends(require_session_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    payload = get_subject_export(user_id)
    ip, ua = _client(request)
    # Journal of actions with personal data (152-FZ art. 19).
    await audit.log(db, action=AuditAction.PD_EXPORT, user_id=user_id, resource_type="subject", resource_id=user_id, ip_address=ip, user_agent=ua)
    return payload


@router.post("/delete")
async def route_subject_delete(
    body: dict,
    request: Request,
    session_id: str = Depends(require_session_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    out = post_subject_delete(body, session_id)
    ip, ua = _client(request)
    await audit.log(db, action=AuditAction.PD_DELETE_REQUEST, user_id=session_id, resource_type="subject", resource_id=session_id, ip_address=ip, user_agent=ua)
    return out


@router.get("/consents")
async def get_my_consents(
    user_id: str = Depends(require_session_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Which texts this person accepted: version, sha256, time; revoked ones marked."""
    return {"consents": await acceptance.list_acceptances(db, user_id)}


@router.post("/consents/{code}/revoke")
async def post_revoke_consent(
    code: str,
    request: Request,
    user_id: str = Depends(require_session_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if code not in acceptance.REVOCABLE_DOCUMENTS:
        raise HTTPException(status_code=404, detail=_MISSING)
    n = await acceptance.revoke(db, user_id, code)
    ip, ua = _client(request)
    await audit.log(db, action=AuditAction.CONSENT_REVOKED, user_id=user_id, resource_type="consent", resource_id=code, ip_address=ip, user_agent=ua)
    await db.commit()
    return {"status": "ok", "revoked": n}


@router.post("/consents/{code}/accept")
async def post_accept_consent(
    code: str,
    request: Request,
    user_id: str = Depends(require_session_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """A separate consent given later (one tick, never pre-checked): stored with version, time, IP."""
    if code not in acceptance.OPTIONAL_DOCUMENTS:
        raise HTTPException(status_code=404, detail=_MISSING)
    if not await acceptance.has_active(db, user_id, code):
        ip, ua = _client(request)
        await acceptance.record_acceptance(db, user_id, code, ip=ip, user_agent=ua)
        await audit.log(db, action=AuditAction.CONSENT_GIVEN, user_id=user_id, resource_type="consent", resource_id=code, ip_address=ip, user_agent=ua)
        await db.commit()
    return {"status": "ok"}
