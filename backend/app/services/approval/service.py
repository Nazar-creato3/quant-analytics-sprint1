"""Persist approval decisions to audit_log and review_queue."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, new_uuid
from app.domain.deal_intent import DealIntentRead
from app.domain.profile import ProfileRead
from app.domain.review_queue import ReviewQueueCreate, ReviewQueueORM, ReviewQueueStatus
from app.services.approval.engine import DealIntentForPolicy, evaluate_policy
from app.services.approval.models import MarketContext, PolicyDecision, PolicyState


class ApprovalPolicyEngine:
    """Evaluate DealIntent policy and persist explainability artifacts."""

    async def evaluate(
        self,
        intent: DealIntentRead | DealIntentForPolicy,
        profile: ProfileRead,
        context: MarketContext,
    ) -> PolicyDecision:
        return evaluate_policy(intent, profile, context)

    async def process(
        self,
        db: AsyncSession,
        *,
        intent: DealIntentRead | DealIntentForPolicy,
        profile: ProfileRead,
        context: MarketContext,
        user_id: str | None = None,
    ) -> PolicyDecision:
        decision = evaluate_policy(intent, profile, context)
        await self._write_audit(db, intent=intent, profile=profile, decision=decision, user_id=user_id)

        if decision.state == PolicyState.HOLD_FOR_REVIEW:
            await self._enqueue_review(db, intent=intent, profile=profile, decision=decision)

        return decision

    async def _write_audit(
        self,
        db: AsyncSession,
        *,
        intent: DealIntentRead | DealIntentForPolicy,
        profile: ProfileRead,
        decision: PolicyDecision,
        user_id: str | None,
    ) -> AuditLog:
        entry = AuditLog(
            id=new_uuid(),
            user_id=user_id or profile.id,
            action=f"approval_policy.{decision.state.value}",
            resource_type="deal_intent",
            resource_id=intent.id,
            details={
                "profile_id": profile.id,
                "sleeve_id": intent.sleeve_id,
                "instrument_id": intent.instrument_id,
                **decision.to_audit_details(),
            },
            success=decision.state != PolicyState.REJECT_HARD,
            error=decision.reason if decision.state == PolicyState.REJECT_HARD else None,
        )
        db.add(entry)
        return entry

    async def _enqueue_review(
        self,
        db: AsyncSession,
        *,
        intent: DealIntentRead | DealIntentForPolicy,
        profile: ProfileRead,
        decision: PolicyDecision,
    ) -> ReviewQueueORM:
        snapshot: dict[str, object]
        if isinstance(intent, DealIntentRead):
            snapshot = intent.model_dump(mode="json")
        else:
            snapshot = {"id": intent.id, "instrument_id": intent.instrument_id}

        payload = ReviewQueueCreate(
            profile_id=profile.id,
            sleeve_id=intent.sleeve_id,
            deal_intent_id=intent.id,
            policy_state=PolicyState.HOLD_FOR_REVIEW.value,
            reason=decision.reason,
            risk_score=decision.risk_score,
            intent_snapshot=snapshot,
        )
        row = ReviewQueueORM(
            profile_id=payload.profile_id,
            sleeve_id=payload.sleeve_id,
            deal_intent_id=payload.deal_intent_id,
            policy_state=payload.policy_state,
            reason=payload.reason,
            risk_score=payload.risk_score,
            intent_snapshot=payload.intent_snapshot,
            status=ReviewQueueStatus.PENDING.value,
        )
        db.add(row)
        return row
