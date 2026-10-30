"""DealIntent approval operations — approve, reject, edit, review queue."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AuditLog, User
from app.domain.deal_intent import DealIntentORM, DealIntentRead, transition_deal_intent_status
from app.domain.deal_intent_enums import (
    DealIntentDirection,
    DealIntentStatus,
    RiskTag,
    TimeInForce,
    TriggerType,
)
from app.domain.deal_intent_fsm import DealIntentEvent, DealIntentTransitionError
from app.domain.review_queue import ReviewQueueORM, ReviewQueueStatus
from app.utils.audit import AuditAction
from app.utils.helpers import utcnow

logger = get_logger(__name__)

_UNSET = object()

_APPROVABLE = (
    DealIntentStatus.PENDING_APPROVAL,
    DealIntentStatus.HELD,
)
_EDITABLE = (
    DealIntentStatus.DRAFT,
    DealIntentStatus.PENDING_APPROVAL,
    DealIntentStatus.HELD,
)
_OPEN_EDITABLE = (
    DealIntentStatus.APPROVED,
    DealIntentStatus.EXECUTING,
    DealIntentStatus.FILLED,
)
_OPEN_EXIT_LOGIC_KEYS = frozenset(
    {"stop_loss", "take_profit", "trailing", "partial_close", "time_exit"}
)


class DealIntentNotFound(RuntimeError):
    def __init__(self, deal_intent_id: str) -> None:
        super().__init__(f"DealIntent {deal_intent_id} not found.")
        self.deal_intent_id = deal_intent_id


class DealIntentOperationError(RuntimeError):
    pass


@dataclass
class DealIntentDecisionResult:
    deal_intent_id: str
    status_before: str
    status_after: str
    action: str
    message: str = ""


async def _load_intent(db: AsyncSession, deal_intent_id: str) -> DealIntentORM:
    result = await db.execute(select(DealIntentORM).where(DealIntentORM.id == deal_intent_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise DealIntentNotFound(deal_intent_id)
    return row


async def _resolve_user(db: AsyncSession, email: str | None) -> User | None:
    if not email:
        return None
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def _write_audit(
    db: AsyncSession,
    *,
    user: User | None,
    action: str,
    deal_intent_id: str,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=action,
            resource_type="deal_intent",
            resource_id=deal_intent_id,
            details=details,
            timestamp=utcnow(),
        )
    )


async def approve_deal_intent(
    db: AsyncSession,
    deal_intent_id: str,
    email: str | None,
    *,
    note: str | None = None,
) -> DealIntentDecisionResult:
    intent = await _load_intent(db, deal_intent_id)
    current = DealIntentStatus(intent.status)
    if current not in _APPROVABLE:
        raise DealIntentOperationError(f"DealIntent in status '{current.value}' cannot be approved.")

    try:
        next_status = transition_deal_intent_status(current, DealIntentEvent.APPROVE)
    except DealIntentTransitionError as exc:
        raise DealIntentOperationError(str(exc)) from exc

    status_before = current.value
    intent.status = next_status.value
    intent.updated_at = utcnow()
    await _resolve_review_queue(db, deal_intent_id)

    user = await _resolve_user(db, email)
    await _write_audit(
        db,
        user=user,
        action=AuditAction.DEAL_INTENT_APPROVE,
        deal_intent_id=deal_intent_id,
        details={"note": note, "status_before": status_before, "status_after": next_status.value},
    )
    await db.commit()

    _notify(
        "deal_intent_approved",
        {"deal_intent_id": deal_intent_id, "status": next_status.value, "owner_email": email},
    )
    return DealIntentDecisionResult(
        deal_intent_id=deal_intent_id,
        status_before=status_before,
        status_after=next_status.value,
        action="approve",
        message="DealIntent approved.",
    )


async def reject_deal_intent(
    db: AsyncSession,
    deal_intent_id: str,
    email: str | None,
    *,
    note: str | None = None,
    reason: str | None = None,
) -> DealIntentDecisionResult:
    intent = await _load_intent(db, deal_intent_id)
    current = DealIntentStatus(intent.status)
    if current not in _APPROVABLE:
        raise DealIntentOperationError(f"DealIntent in status '{current.value}' cannot be rejected.")

    try:
        next_status = transition_deal_intent_status(current, DealIntentEvent.REJECT)
    except DealIntentTransitionError as exc:
        raise DealIntentOperationError(str(exc)) from exc

    status_before = current.value
    intent.status = next_status.value
    intent.updated_at = utcnow()
    exit_logic = dict(intent.exit_logic or {})
    if reason:
        exit_logic["reject_reason"] = reason
    if note:
        exit_logic["reject_note"] = note
    intent.exit_logic = exit_logic
    await _resolve_review_queue(db, deal_intent_id)

    user = await _resolve_user(db, email)
    await _write_audit(
        db,
        user=user,
        action=AuditAction.DEAL_INTENT_REJECT,
        deal_intent_id=deal_intent_id,
        details={"note": note, "reason": reason, "status_before": status_before, "status_after": next_status.value},
    )
    await db.commit()

    _notify(
        "deal_intent_rejected",
        {"deal_intent_id": deal_intent_id, "status": next_status.value, "owner_email": email},
    )
    return DealIntentDecisionResult(
        deal_intent_id=deal_intent_id,
        status_before=status_before,
        status_after=next_status.value,
        action="reject",
        message="DealIntent rejected.",
    )


async def edit_deal_intent(
    db: AsyncSession,
    deal_intent_id: str,
    email: str | None,
    *,
    target_price: Decimal | None = None,
    direction: str | None = None,
    required_confidence: float | None = None,
    max_slippage_bps: int | None = None,
    max_spread_bps: int | None = None,
    time_in_force: str | None = None,
    trigger_type: str | None = None,
    approval_threshold: Decimal | None = None,
    risk_tag: str | None = None,
    hedge_attachment_id: str | None | object = _UNSET,
    exit_logic: dict[str, Any] | None = None,
    note: str | None = None,
) -> DealIntentRead:
    intent = await _load_intent(db, deal_intent_id)
    current = DealIntentStatus(intent.status)
    is_open = current in _OPEN_EDITABLE
    if current not in _EDITABLE and not is_open:
        raise DealIntentOperationError(f"DealIntent in status '{current.value}' cannot be edited.")

    pre_fields = {
        "target_price": target_price,
        "direction": direction,
        "required_confidence": required_confidence,
        "max_slippage_bps": max_slippage_bps,
        "max_spread_bps": max_spread_bps,
        "time_in_force": time_in_force,
        "trigger_type": trigger_type,
        "approval_threshold": approval_threshold,
        "risk_tag": risk_tag,
    }
    hedge_provided = hedge_attachment_id is not _UNSET
    if is_open:
        blocked = [k for k, v in pre_fields.items() if v is not None]
        if hedge_provided:
            blocked.append("hedge_attachment_id")
        if blocked:
            raise DealIntentOperationError(
                "Open positions allow exit controls only (TP/SL/trailing/partial close/duration)."
            )
        if exit_logic is not None:
            disallowed = set(exit_logic.keys()) - _OPEN_EXIT_LOGIC_KEYS
            if disallowed:
                raise DealIntentOperationError(
                    f"Open positions cannot edit exit_logic keys: {sorted(disallowed)}"
                )

    changes: dict[str, Any] = {}
    if target_price is not None:
        intent.target_price = target_price
        changes["target_price"] = str(target_price)
    if direction is not None:
        intent.direction = DealIntentDirection(direction).value
        changes["direction"] = intent.direction
    if required_confidence is not None:
        intent.required_confidence = required_confidence
        changes["required_confidence"] = required_confidence
    if max_slippage_bps is not None:
        intent.max_slippage_bps = max_slippage_bps
        changes["max_slippage_bps"] = max_slippage_bps
    if max_spread_bps is not None:
        intent.max_spread_bps = max_spread_bps
        changes["max_spread_bps"] = max_spread_bps
    if time_in_force is not None:
        intent.time_in_force = TimeInForce(time_in_force).value
        changes["time_in_force"] = intent.time_in_force
    if trigger_type is not None:
        intent.trigger_type = TriggerType(trigger_type).value
        changes["trigger_type"] = intent.trigger_type
    if approval_threshold is not None:
        intent.approval_threshold = approval_threshold
        changes["approval_threshold"] = str(approval_threshold)
    if risk_tag is not None:
        intent.risk_tag = RiskTag(risk_tag).value
        changes["risk_tag"] = intent.risk_tag
    if hedge_provided:
        normalized = hedge_attachment_id.strip() or None if isinstance(hedge_attachment_id, str) else None
        intent.hedge_attachment_id = normalized
        changes["hedge_attachment_id"] = normalized
    if exit_logic is not None:
        merged = dict(intent.exit_logic or {})
        merged.update(exit_logic)
        intent.exit_logic = merged
        changes["exit_logic"] = exit_logic

    if not changes:
        raise DealIntentOperationError("No editable fields provided.")

    intent.updated_at = utcnow()
    user = await _resolve_user(db, email)
    await _write_audit(
        db,
        user=user,
        action=AuditAction.DEAL_INTENT_EDIT,
        deal_intent_id=deal_intent_id,
        details={"changes": changes, "note": note},
    )
    await db.commit()
    await db.refresh(intent)
    return DealIntentRead.from_orm_row(intent)


async def _resolve_review_queue(db: AsyncSession, deal_intent_id: str) -> None:
    result = await db.execute(
        select(ReviewQueueORM).where(
            ReviewQueueORM.deal_intent_id == deal_intent_id,
            ReviewQueueORM.status == ReviewQueueStatus.PENDING.value,
        )
    )
    for row in result.scalars().all():
        row.status = ReviewQueueStatus.RESOLVED.value
        row.resolved_at = utcnow()


def _notify(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from app.utils.ws_notify import notify_pipeline_sync

        notify_pipeline_sync(event_type, payload)
    except Exception as exc:
        logger.warning("Approval WS notify failed", event=event_type, error=str(exc))
