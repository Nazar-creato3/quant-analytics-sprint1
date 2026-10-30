"""ControlFabric — top-layer orchestration of risk, kill switch, audit, and replay."""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.deal_intent import DealIntentRead
from app.domain.profile import ProfileRead
from app.domain.sleeve import SleeveRead
from app.services.approval.models import MarketContext, PolicyDecision
from app.services.approval.orchestrator import ApprovalOrchestrator
from app.services.control_fabric.audit_journal import AuditJournal
from app.services.control_fabric.kill_switch import KillSwitchService
from app.services.control_fabric.replay_engine import ReplayEngine
from app.services.control_fabric.risk_gate import RiskGate
from app.services.control_fabric.types import (
    KillSwitchScope,
    KillSwitchTrigger,
    OpenPositionExposure,
    ReplayIntentRecord,
    ReplayReport,
    RiskGateResult,
    RiskSnapshot,
)


class ControlFabricResult:
    """Outcome of processing a DealIntent through ControlFabric."""

    __slots__ = (
        "blocked_by_kill_switch",
        "kill_switch_triggered",
        "risk_gate",
        "approval_decision",
    )

    def __init__(
        self,
        *,
        blocked_by_kill_switch: bool = False,
        kill_switch_triggered: bool = False,
        risk_gate: RiskGateResult | None = None,
        approval_decision: PolicyDecision | None = None,
    ) -> None:
        self.blocked_by_kill_switch = blocked_by_kill_switch
        self.kill_switch_triggered = kill_switch_triggered
        self.risk_gate = risk_gate
        self.approval_decision = approval_decision

    @property
    def allowed(self) -> bool:
        if self.blocked_by_kill_switch or self.kill_switch_triggered:
            return False
        if self.risk_gate is not None and not self.risk_gate.allowed:
            return False
        if self.approval_decision is not None:
            return self.approval_decision.is_approvable
        return False


class ControlFabric:
    """Top layer: KillSwitch → RiskGate → ApprovalPolicyEngine → AuditJournal."""

    def __init__(
        self,
        *,
        risk_gate: RiskGate | None = None,
        kill_switch: KillSwitchService | None = None,
        audit: AuditJournal | None = None,
        approval: ApprovalOrchestrator | None = None,
        replay: ReplayEngine | None = None,
    ) -> None:
        self.risk_gate = risk_gate or RiskGate()
        self.kill_switch = kill_switch or KillSwitchService()
        self.audit = audit or AuditJournal()
        self.approval = approval or ApprovalOrchestrator()
        self.replay = replay or ReplayEngine(risk_gate=self.risk_gate)

    async def process_intent(
        self,
        db: AsyncSession,
        *,
        intent: DealIntentRead,
        profile: ProfileRead,
        sleeve: SleeveRead,
        context: MarketContext,
        user_id: str | None = None,
        actor: str | None = None,
        source: str = "strategy_mesh",
        snapshot: RiskSnapshot | None = None,
        open_positions: Sequence[OpenPositionExposure] = (),
        instrument_correlations: dict[int, float] | None = None,
        atr: float = 0.0,
        price: float = 0.0,
        base_size_usd: Decimal | None = None,
        auto_kill_on_breach: bool = True,
    ) -> ControlFabricResult:
        actor_id = actor or user_id or profile.id

        await self.audit.log_intent_created(
            db,
            intent=intent,
            profile=profile,
            actor=actor_id,
            source=source,
        )

        ks_status = await self.kill_switch.is_active(
            db,
            profile_id=profile.id,
            sleeve_id=sleeve.id,
        )
        if ks_status.active:
            await self.audit.append(
                db,
                action="control_fabric.blocked_by_kill_switch",
                user_id=actor_id,
                resource_type="deal_intent",
                resource_id=intent.id,
                details={
                    "scope": ks_status.scope.value,
                    "scope_id": ks_status.scope_id,
                    "reason": ks_status.reason,
                },
                success=False,
                error=ks_status.reason,
            )
            return ControlFabricResult(blocked_by_kill_switch=True)

        risk_result = self.risk_gate.check_intent(
            intent,
            profile,
            sleeve,
            context,
            snapshot=snapshot,
            open_positions=open_positions,
            instrument_correlations=instrument_correlations,
            atr=atr,
            price=price,
            base_size_usd=base_size_usd,
        )
        await self.audit.log_risk_gate(
            db,
            intent_id=intent.id,
            profile_id=profile.id,
            result=risk_result,
            user_id=actor_id,
        )

        if risk_result.triggers_kill_switch and auto_kill_on_breach:
            ks_row = await self.kill_switch.trigger(
                db,
                scope=KillSwitchScope.PROFILE,
                scope_id=profile.id,
                reason=risk_result.reason,
                trigger_type=KillSwitchTrigger.AUTO,
                triggered_by=actor_id,
            )
            await self.audit.log_kill_switch_triggered(
                db,
                scope=KillSwitchScope.PROFILE,
                scope_id=profile.id,
                trigger_type=KillSwitchTrigger.AUTO,
                reason=risk_result.reason,
                triggered_by=actor_id,
            )
            return ControlFabricResult(
                kill_switch_triggered=True,
                risk_gate=risk_result,
            )

        if not risk_result.allowed:
            return ControlFabricResult(risk_gate=risk_result)

        decision = await self.approval.process_and_apply(
            db,
            intent=intent,
            profile=profile,
            context=context,
            user_id=user_id,
        )
        await self.audit.log_approval_decision(
            db,
            intent_id=intent.id,
            profile=profile,
            decision=decision,
            user_id=actor_id,
        )

        return ControlFabricResult(risk_gate=risk_result, approval_decision=decision)

    async def trigger_kill_switch(
        self,
        db: AsyncSession,
        *,
        scope: KillSwitchScope,
        scope_id: str | None,
        reason: str,
        trigger_type: KillSwitchTrigger = KillSwitchTrigger.MANUAL,
        triggered_by: str | None = None,
    ) -> None:
        await self.kill_switch.trigger(
            db,
            scope=scope,
            scope_id=scope_id,
            reason=reason,
            trigger_type=trigger_type,
            triggered_by=triggered_by,
        )
        await self.audit.log_kill_switch_triggered(
            db,
            scope=scope,
            scope_id=scope_id,
            trigger_type=trigger_type,
            reason=reason,
            triggered_by=triggered_by,
        )

    async def unlock_kill_switch(
        self,
        db: AsyncSession,
        *,
        scope: KillSwitchScope,
        scope_id: str | None,
        comment: str,
        unlocked_by: str | None = None,
    ) -> None:
        await self.kill_switch.unlock(
            db,
            scope=scope,
            scope_id=scope_id,
            comment=comment,
            unlocked_by=unlocked_by,
        )
        await self.audit.log_kill_switch_unlocked(
            db,
            scope=scope,
            scope_id=scope_id,
            comment=comment,
            unlocked_by=unlocked_by,
        )

    def run_replay(
        self,
        records: Sequence[ReplayIntentRecord],
        *,
        profiles: dict[str, ProfileRead],
        sleeves: dict[str, SleeveRead],
        expected_decisions: dict[str, dict[str, str]] | None = None,
    ) -> ReplayReport:
        return self.replay.replay(
            records,
            profiles=profiles,
            sleeves=sleeves,
            expected_decisions=expected_decisions,
        )
