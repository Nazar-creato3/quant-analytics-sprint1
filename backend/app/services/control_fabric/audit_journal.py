"""Append-only audit journal for ControlFabric explainability."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, new_uuid
from app.domain.deal_intent import DealIntentRead
from app.domain.profile import ProfileRead
from app.services.approval.models import PolicyDecision
from app.services.control_fabric.types import KillSwitchScope, KillSwitchTrigger, RiskGateResult


class ControlFabricAuditAction:
    INTENT_CREATED = "control_fabric.intent_created"
    RISK_GATE = "control_fabric.risk_gate"
    APPROVAL_POLICY = "control_fabric.approval_policy"
    EXECUTION = "control_fabric.execution"
    KILL_SWITCH_TRIGGERED = "control_fabric.kill_switch_triggered"
    KILL_SWITCH_UNLOCKED = "control_fabric.kill_switch_unlocked"
    REPLAY = "control_fabric.replay"


class AuditJournal:
    """Immutable append-only journal — inserts only, never updates or deletes."""

    async def append(
        self,
        db: AsyncSession,
        *,
        action: str,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            id=new_uuid(),
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            success=success,
            error=error,
        )
        db.add(entry)
        return entry

    async def log_intent_created(
        self,
        db: AsyncSession,
        *,
        intent: DealIntentRead,
        profile: ProfileRead,
        actor: str,
        source: str,
    ) -> AuditLog:
        return await self.append(
            db,
            action=ControlFabricAuditAction.INTENT_CREATED,
            user_id=actor,
            resource_type="deal_intent",
            resource_id=intent.id,
            details={
                "profile_id": profile.id,
                "sleeve_id": intent.sleeve_id,
                "instrument_id": intent.instrument_id,
                "source": source,
                "intent_snapshot": intent.model_dump(mode="json"),
            },
        )

    async def log_risk_gate(
        self,
        db: AsyncSession,
        *,
        intent_id: str,
        profile_id: str,
        result: RiskGateResult,
        user_id: str | None = None,
    ) -> AuditLog:
        details: dict[str, Any] = {
            "profile_id": profile_id,
            "outcome": result.outcome.value,
            "allowed": result.allowed,
            "reason": result.reason,
            "metadata": result.metadata,
        }
        if result.position_size is not None:
            details["position_size"] = {
                "base_size_usd": str(result.position_size.base_size_usd),
                "adjusted_size_usd": str(result.position_size.adjusted_size_usd),
                "atr": result.position_size.atr,
                "atr_pct": result.position_size.atr_pct,
                "scale_factor": result.position_size.scale_factor,
                "reason": result.position_size.reason,
            }
        return await self.append(
            db,
            action=ControlFabricAuditAction.RISK_GATE,
            user_id=user_id or profile_id,
            resource_type="deal_intent",
            resource_id=intent_id,
            details=details,
            success=result.allowed,
            error=None if result.allowed else result.reason,
        )

    async def log_approval_decision(
        self,
        db: AsyncSession,
        *,
        intent_id: str,
        profile: ProfileRead,
        decision: PolicyDecision,
        user_id: str | None = None,
    ) -> AuditLog:
        return await self.append(
            db,
            action=ControlFabricAuditAction.APPROVAL_POLICY,
            user_id=user_id or profile.id,
            resource_type="deal_intent",
            resource_id=intent_id,
            details={
                "profile_id": profile.id,
                **decision.to_audit_details(),
            },
            success=decision.is_approvable,
            error=decision.reason if not decision.is_approvable else None,
        )

    async def log_execution(
        self,
        db: AsyncSession,
        *,
        intent_id: str,
        profile_id: str,
        execution_details: dict[str, Any],
        user_id: str | None = None,
    ) -> AuditLog:
        return await self.append(
            db,
            action=ControlFabricAuditAction.EXECUTION,
            user_id=user_id or profile_id,
            resource_type="deal_intent",
            resource_id=intent_id,
            details={"profile_id": profile_id, **execution_details},
        )

    async def log_kill_switch_triggered(
        self,
        db: AsyncSession,
        *,
        scope: KillSwitchScope,
        scope_id: str | None,
        trigger_type: KillSwitchTrigger,
        reason: str,
        triggered_by: str | None = None,
        cancelled_intents: int = 0,
    ) -> AuditLog:
        return await self.append(
            db,
            action=ControlFabricAuditAction.KILL_SWITCH_TRIGGERED,
            user_id=triggered_by,
            resource_type="kill_switch",
            resource_id=scope_id,
            details={
                "scope": scope.value,
                "scope_id": scope_id,
                "trigger_type": trigger_type.value,
                "reason": reason,
                "cancelled_intents": cancelled_intents,
            },
            success=False,
            error=reason,
        )

    async def log_kill_switch_unlocked(
        self,
        db: AsyncSession,
        *,
        scope: KillSwitchScope,
        scope_id: str | None,
        comment: str,
        unlocked_by: str | None = None,
    ) -> AuditLog:
        return await self.append(
            db,
            action=ControlFabricAuditAction.KILL_SWITCH_UNLOCKED,
            user_id=unlocked_by,
            resource_type="kill_switch",
            resource_id=scope_id,
            details={
                "scope": scope.value,
                "scope_id": scope_id,
                "unlock_comment": comment,
            },
        )

    async def fetch_trail(
        self,
        db: AsyncSession,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        actions: tuple[str, ...] | None = None,
    ) -> list[AuditLog]:
        query = select(AuditLog).order_by(AuditLog.timestamp.asc())
        if resource_type:
            query = query.where(AuditLog.resource_type == resource_type)
        if resource_id:
            query = query.where(AuditLog.resource_id == resource_id)
        if actions:
            query = query.where(AuditLog.action.in_(actions))
        result = await db.execute(query)
        return list(result.scalars().all())
