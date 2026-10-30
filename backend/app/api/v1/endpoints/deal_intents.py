"""DealIntent lifecycle endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_user_db
from app.domain.deal_intent import DealIntentORM, DealIntentRead
from app.domain.review_queue import ReviewQueueORM, ReviewQueueRead, ReviewQueueStatus
from app.schemas.schemas import (
    DealIntentApprovalRequest,
    DealIntentApprovalOut,
    DealIntentCancelOut,
    DealIntentCancelRequest,
    DealIntentEditRequest,
    PaginatedResponse,
)
from app.services.approval.deal_intent_ops import (
    DealIntentNotFound,
    DealIntentOperationError,
    approve_deal_intent,
    edit_deal_intent,
    reject_deal_intent,
)
from app.services.portfolio.cancel_deal_intent import (
    DealIntentNotCancellable,
    cancel_deal_intent,
)

router = APIRouter(prefix="/deal-intents", tags=["deal-intents"])


async def _require_deal_intent_for_user(
    db: AsyncSession,
    email: str,
    deal_intent_id: str,
) -> DealIntentORM:
    """Load a deal intent scoped to the caller; 404 when out of scope."""
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import is_staff_admin_role
    from app.services.portfolio.user_scope import get_user_by_email, load_deal_intent_for_user

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    _user, role = await get_user_and_role(db, email)
    row = await load_deal_intent_for_user(
        db,
        user.id,
        deal_intent_id,
        staff_all=is_staff_admin_role(role),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Намерение не найдено")
    return row


@router.get("", response_model=PaginatedResponse)
async def list_deal_intents(
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> PaginatedResponse:
    """List DealIntents with optional status filter."""
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import is_staff_admin_role
    from app.services.portfolio.user_scope import deal_intents_for_user, get_user_by_email

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    _user, role = await get_user_and_role(db, email)
    query = deal_intents_for_user(
        user.id,
        staff_all=is_staff_admin_role(role),
    ).order_by(desc(DealIntentORM.created_at))
    if status_filter:
        if "," in status_filter:
            statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
            query = query.where(DealIntentORM.status.in_(statuses))
        else:
            query = query.where(DealIntentORM.status == status_filter)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    rows = result.scalars().all()
    items = [DealIntentRead.from_orm_row(r).model_dump() for r in rows]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


@router.get("/review-queue", response_model=list[ReviewQueueRead])
async def list_review_queue(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> list[ReviewQueueRead]:
    """List pending manual review items (staff)."""
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import is_staff_admin_role

    _user, role = await get_user_and_role(db, email)
    if not is_staff_admin_role(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нужны права сотрудника")
    result = await db.execute(
        select(ReviewQueueORM)
        .where(ReviewQueueORM.status == ReviewQueueStatus.PENDING.value)
        .order_by(desc(ReviewQueueORM.created_at))
    )
    return [
        ReviewQueueRead(
            id=r.id,
            profile_id=r.profile_id,
            sleeve_id=r.sleeve_id,
            deal_intent_id=r.deal_intent_id,
            policy_state=r.policy_state,
            reason=r.reason,
            risk_score=r.risk_score,
            intent_snapshot=r.intent_snapshot or {},
            status=ReviewQueueStatus(r.status),
            created_at=r.created_at,
            resolved_at=r.resolved_at,
        )
        for r in result.scalars().all()
    ]


@router.get("/{deal_intent_id}", response_model=DealIntentRead)
async def get_deal_intent(
    deal_intent_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> DealIntentRead:
    row = await _require_deal_intent_for_user(db, email, deal_intent_id)
    return DealIntentRead.from_orm_row(row)


@router.post("/{deal_intent_id}/approve", response_model=DealIntentApprovalOut)
async def approve_deal_intent_endpoint(
    deal_intent_id: str,
    body: DealIntentApprovalRequest | None = None,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> DealIntentApprovalOut:
    payload = body or DealIntentApprovalRequest(action="approve")
    if payload.action != "approve":
        raise HTTPException(status_code=400, detail="Для отклонения используйте другой запрос.")
    await _require_deal_intent_for_user(db, email, deal_intent_id)
    try:
        from app.services.pretrade.policy import evaluate

        evaluate(kind="idea", actor="human", user_id=email, ticker="IDEA", qty=1.0, price=1.0)
        result = await approve_deal_intent(db, deal_intent_id, email, note=payload.note)
    except DealIntentNotFound:
        raise HTTPException(status_code=404, detail="Намерение не найдено")
    except DealIntentOperationError as exc:
        raise HTTPException(status_code=409, detail="Сейчас это действие недоступно.")
    return DealIntentApprovalOut(
        deal_intent_id=result.deal_intent_id,
        status_before=result.status_before,
        status_after=result.status_after,
        action=result.action,
        message=result.message,
    )


@router.post("/{deal_intent_id}/reject", response_model=DealIntentApprovalOut)
async def reject_deal_intent_endpoint(
    deal_intent_id: str,
    body: DealIntentApprovalRequest | None = None,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> DealIntentApprovalOut:
    payload = body or DealIntentApprovalRequest(action="reject")
    await _require_deal_intent_for_user(db, email, deal_intent_id)
    try:
        result = await reject_deal_intent(
            db, deal_intent_id, email, note=payload.note, reason=payload.reason
        )
    except DealIntentNotFound:
        raise HTTPException(status_code=404, detail="Намерение не найдено")
    except DealIntentOperationError as exc:
        raise HTTPException(status_code=409, detail="Сейчас это действие недоступно.")
    return DealIntentApprovalOut(
        deal_intent_id=result.deal_intent_id,
        status_before=result.status_before,
        status_after=result.status_after,
        action=result.action,
        message=result.message,
    )


@router.patch("/{deal_intent_id}", response_model=DealIntentRead)
async def edit_deal_intent_endpoint(
    deal_intent_id: str,
    body: DealIntentEditRequest,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> DealIntentRead:
    """Edit DealIntent fields before approval or exit controls on open positions."""
    from decimal import Decimal

    await _require_deal_intent_for_user(db, email, deal_intent_id)
    edit_kwargs: dict[str, object] = {
        "target_price": Decimal(str(body.target_price)) if body.target_price is not None else None,
        "direction": body.direction,
        "required_confidence": body.required_confidence,
        "max_slippage_bps": body.max_slippage_bps,
        "max_spread_bps": body.max_spread_bps,
        "time_in_force": body.time_in_force,
        "trigger_type": body.trigger_type,
        "approval_threshold": (
            Decimal(str(body.approval_threshold)) if body.approval_threshold is not None else None
        ),
        "risk_tag": body.risk_tag,
        "exit_logic": body.exit_logic,
        "note": body.note,
    }
    if "hedge_attachment_id" in body.model_fields_set:
        edit_kwargs["hedge_attachment_id"] = body.hedge_attachment_id

    try:
        return await edit_deal_intent(db, deal_intent_id, email, **edit_kwargs)  # type: ignore[arg-type]
    except DealIntentNotFound:
        raise HTTPException(status_code=404, detail="Намерение не найдено")
    except DealIntentOperationError as exc:
        raise HTTPException(status_code=409, detail="Сейчас это действие недоступно.")


@router.post("/{deal_intent_id}/cancel", response_model=DealIntentCancelOut)
async def cancel_deal_intent_endpoint(
    deal_intent_id: str,
    body: DealIntentCancelRequest | None = None,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> DealIntentCancelOut:
    """Cancel one DealIntent via FSM cancel transition."""
    payload = body or DealIntentCancelRequest()
    await _require_deal_intent_for_user(db, email, deal_intent_id)
    try:
        result = await cancel_deal_intent(
            db,
            deal_intent_id,
            email,
            reason=payload.reason or "operator cancel",
            note=payload.note,
        )
    except DealIntentNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Намерение не найдено")
    except DealIntentNotCancellable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Сейчас это действие недоступно.")

    return DealIntentCancelOut(
        deal_intent_id=result.deal_intent_id,
        status_before=result.status_before,
        status_after=result.status_after,
        message=result.message,
    )


@router.get("/{deal_intent_id}/compliance-report.pdf")
async def download_compliance_report_pdf(
    deal_intent_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> Response:
    """Download a 39-FZ compliance PDF for a DealIntent recommendation."""
    from app.services.compliance_report.pdf_renderer import render_compliance_pdf
    from app.services.compliance_report.service import (
        ComplianceReportNotFoundError,
        ComplianceReportService,
    )

    await _require_deal_intent_for_user(db, email, deal_intent_id)
    service = ComplianceReportService()
    try:
        document = await service.build_document(db, deal_intent_id)
    except ComplianceReportNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Намерение не найдено")

    pdf_bytes = render_compliance_pdf(document)
    filename = f"compliance-report-{deal_intent_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
