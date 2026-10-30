"""Cancel a single DealIntent via the FSM cancel transition."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AuditLog, User
from app.domain.deal_intent import DealIntentORM, transition_deal_intent_status
from app.domain.deal_intent_enums import DealIntentStatus, TERMINAL_DEAL_INTENT_STATUSES
from app.domain.deal_intent_fsm import DealIntentEvent, DealIntentTransitionError
from app.utils.audit import AuditAction
from app.utils.helpers import utcnow

logger = get_logger(__name__)

_CANCELLABLE_STATUSES = (
    DealIntentStatus.DRAFT,
    DealIntentStatus.PENDING_APPROVAL,
    DealIntentStatus.APPROVED,
    DealIntentStatus.HELD,
    DealIntentStatus.EXECUTING,
)


class DealIntentNotFound(RuntimeError):
    def __init__(self, deal_intent_id: str) -> None:
        super().__init__(f"DealIntent {deal_intent_id} not found.")
        self.deal_intent_id = deal_intent_id


class DealIntentNotCancellable(RuntimeError):
    def __init__(self, deal_intent_id: str, status: str) -> None:
        super().__init__(f"DealIntent {deal_intent_id} in status '{status}' cannot be cancelled.")
        self.deal_intent_id = deal_intent_id
        self.status = status


@dataclass
class CancelDealIntentResult:
    deal_intent_id: str
    status_before: str
    status_after: str
    message: str = ""


async def cancel_deal_intent(
    db: AsyncSession,
    deal_intent_id: str,
    email: str | None,
    *,
    reason: str = "operator cancel",
    note: str | None = None,
) -> CancelDealIntentResult:
    """Apply DealIntentEvent.CANCEL to one intent."""
    result = await db.execute(select(DealIntentORM).where(DealIntentORM.id == deal_intent_id))
    intent_row = result.scalar_one_or_none()
    if intent_row is None:
        raise DealIntentNotFound(deal_intent_id)

    current = DealIntentStatus(intent_row.status)
    if current in TERMINAL_DEAL_INTENT_STATUSES or current not in _CANCELLABLE_STATUSES:
        raise DealIntentNotCancellable(deal_intent_id, current.value)

    try:
        next_status = transition_deal_intent_status(current, DealIntentEvent.CANCEL)
    except DealIntentTransitionError as exc:
        raise DealIntentNotCancellable(deal_intent_id, current.value) from exc

    status_before = current.value
    intent_row.status = next_status.value
    intent_row.updated_at = utcnow()
    exit_logic = dict(intent_row.exit_logic or {})
    exit_logic["cancel_reason"] = reason
    if note:
        exit_logic["cancel_note"] = note
    intent_row.exit_logic = exit_logic

    user = None
    if email:
        user_result = await db.execute(select(User).where(User.email == email))
        user = user_result.scalar_one_or_none()

    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=AuditAction.DEAL_INTENT_CANCEL,
            resource_type="deal_intent",
            resource_id=deal_intent_id,
            details={
                "reason": reason,
                "note": note,
                "status_before": status_before,
                "status_after": next_status.value,
            },
        )
    )
    await db.commit()

    logger.info(
        "DealIntent cancelled individually",
        deal_intent_id=deal_intent_id,
        status_before=status_before,
        status_after=next_status.value,
    )

    return CancelDealIntentResult(
        deal_intent_id=deal_intent_id,
        status_before=status_before,
        status_after=next_status.value,
        message="DealIntent отменён.",
    )
