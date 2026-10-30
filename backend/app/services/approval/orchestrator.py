"""Apply ApprovalPolicyEngine decisions to DealIntent lifecycle and sleeve state."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.deal_intent import DealIntentORM, DealIntentRead, transition_deal_intent_status
from app.domain.deal_intent_enums import DealIntentStatus
from app.domain.deal_intent_fsm import DealIntentEvent
from app.domain.enums import SleeveStatus
from app.domain.profile import ProfileORM, ProfileRead
from app.domain.sleeve import SleeveORM
from app.services.approval.models import MarketContext, PolicyDecision, PolicyState
from app.services.approval.service import ApprovalPolicyEngine
from app.utils.helpers import utcnow


_ACTIVE_INTENT_STATUSES = (
    DealIntentStatus.PENDING_APPROVAL.value,
    DealIntentStatus.EXECUTING.value,
)


class ApprovalOrchestrator:
    """Evaluate policy and mutate DealIntent / sleeve / session state."""

    def __init__(self, engine: ApprovalPolicyEngine | None = None) -> None:
        self._engine = engine or ApprovalPolicyEngine()

    async def process_and_apply(
        self,
        db: AsyncSession,
        *,
        intent: DealIntentRead,
        profile: ProfileRead,
        context: MarketContext,
        user_id: str | None = None,
    ) -> PolicyDecision:
        decision = await self._engine.process(
            db,
            intent=intent,
            profile=profile,
            context=context,
            user_id=user_id,
        )
        await self.apply_decision(
            db,
            intent_id=intent.id,
            sleeve_id=intent.sleeve_id,
            profile=profile,
            decision=decision,
        )
        return decision

    async def apply_decision(
        self,
        db: AsyncSession,
        *,
        intent_id: str,
        sleeve_id: str,
        profile: ProfileRead,
        decision: PolicyDecision,
    ) -> None:
        if decision.state == PolicyState.KILL_SESSION:
            await self._kill_profile_session(db, profile.id, decision.reason)
            return

        if decision.state == PolicyState.FREEZE_SLEEVE:
            await self._freeze_sleeve(db, sleeve_id, decision.reason)
            await self._hold_sleeve_intents(db, sleeve_id, decision.reason)
            return

        if decision.state in {PolicyState.AUTO_APPROVE, PolicyState.CONDITIONAL_APPROVE}:
            await self._transition_intent(
                db,
                intent_id,
                DealIntentEvent.APPROVE,
                decision.reason,
            )
        elif decision.state == PolicyState.REJECT_HARD:
            await self._transition_intent(
                db,
                intent_id,
                DealIntentEvent.REJECT,
                decision.reason,
            )
        elif decision.state == PolicyState.HOLD_FOR_REVIEW:
            await self._transition_intent(
                db,
                intent_id,
                DealIntentEvent.HOLD,
                decision.reason,
            )

    async def _transition_intent(
        self,
        db: AsyncSession,
        intent_id: str,
        event: DealIntentEvent,
        reason: str,
    ) -> None:
        row = await self._load_intent(db, intent_id)
        if row is None:
            return
        current = DealIntentStatus(row.status)
        try:
            next_status = transition_deal_intent_status(current, event)
        except ValueError:
            return
        row.status = next_status.value
        row.updated_at = utcnow()
        exit_logic = dict(row.exit_logic or {})
        exit_logic["last_approval_reason"] = reason
        row.exit_logic = exit_logic

    async def _hold_sleeve_intents(
        self,
        db: AsyncSession,
        sleeve_id: str,
        reason: str,
    ) -> None:
        result = await db.execute(
            select(DealIntentORM).where(
                DealIntentORM.sleeve_id == sleeve_id,
                DealIntentORM.status == DealIntentStatus.PENDING_APPROVAL.value,
            )
        )
        for row in result.scalars().all():
            await self._transition_intent(db, row.id, DealIntentEvent.HOLD, reason)

    async def _freeze_sleeve(
        self,
        db: AsyncSession,
        sleeve_id: str,
        reason: str,
    ) -> None:
        await db.execute(
            update(SleeveORM)
            .where(SleeveORM.id == sleeve_id)
            .values(status=SleeveStatus.FROZEN.value, updated_at=utcnow())
        )

    async def _kill_profile_session(
        self,
        db: AsyncSession,
        profile_id: str,
        reason: str,
    ) -> None:
        profile_row = await self._load_profile(db, profile_id)
        if profile_row is None:
            return

        prefs: dict[str, Any] = deepcopy(profile_row.session_preferences or {})
        prefs["session_killed"] = True
        prefs["session_kill_reason"] = reason
        prefs["session_killed_at"] = utcnow().isoformat()
        profile_row.session_preferences = prefs
        profile_row.updated_at = utcnow()

        result = await db.execute(
            select(DealIntentORM)
            .join(SleeveORM, DealIntentORM.sleeve_id == SleeveORM.id)
            .where(
                SleeveORM.profile_id == profile_id,
                DealIntentORM.status.in_(_ACTIVE_INTENT_STATUSES),
            )
        )
        for row in result.scalars().all():
            current = DealIntentStatus(row.status)
            event = DealIntentEvent.HOLD if current == DealIntentStatus.PENDING_APPROVAL else DealIntentEvent.CANCEL
            try:
                next_status = transition_deal_intent_status(current, event)
            except ValueError:
                continue
            row.status = next_status.value
            row.updated_at = utcnow()

    async def _load_intent(self, db: AsyncSession, intent_id: str) -> DealIntentORM | None:
        result = await db.execute(select(DealIntentORM).where(DealIntentORM.id == intent_id))
        return result.scalar_one_or_none()

    async def _load_profile(self, db: AsyncSession, profile_id: str) -> ProfileORM | None:
        result = await db.execute(select(ProfileORM).where(ProfileORM.id == profile_id))
        return result.scalar_one_or_none()
