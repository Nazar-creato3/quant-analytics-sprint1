"""SleeveEngine — capital allocation, risk budget, and rebalance planning."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from app.domain.enums import SleeveStatus, Strategy
from app.domain.profile import ProfileBase, ProfileMode
from app.domain.sleeve import SleeveRead
from app.services.sleeve.risk_budget import (
    build_risk_budget_rebalance_plan,
    risk_budget_allocation,
)
from app.services.compliance.access_layer import check_instrument_access
from app.services.sleeve.types import (
    BasketInstrumentTarget,
    ComplianceIntentRequest,
    CustomBasketSnapshot,
    IntentRiskRequest,
    RebalanceAction,
    RebalanceAdjustment,
    RebalancePlan,
    RiskBudgetAllocation,
    RiskBudgetRebalancePlan,
    SleeveCapitalAllocation,
    SleeveGateResult,
    SleevePositionSnapshot,
)

_REBALANCE_HOLD_TOLERANCE_USD = Decimal("1.00")


class SleeveEngine:
    """Distributes profile capital across sleeves and gates new deal intents."""

    def __init__(self, total_capital_usd: Decimal | float) -> None:
        self.total_capital_usd = Decimal(str(total_capital_usd))

    def allocation_targets(
        self,
        sleeves: Sequence[SleeveRead],
        *,
        positions: Sequence[SleevePositionSnapshot] = (),
        pending_intents: Sequence[IntentRiskRequest] = (),
    ) -> list[SleeveCapitalAllocation]:
        """Target capital per sleeve from ``capital_allocation_pct`` and risk usage."""
        risk_by_sleeve = self.risk_usage_by_sleeve(positions, pending_intents)
        return [
            self._allocation_row(sleeve, risk_by_sleeve.get(sleeve.id, Decimal("0")))
            for sleeve in sleeves
        ]

    def risk_usage_by_sleeve(
        self,
        positions: Sequence[SleevePositionSnapshot],
        pending_intents: Sequence[IntentRiskRequest] | None = None,
    ) -> dict[str, Decimal]:
        """Aggregate consumed risk budget per sleeve."""
        usage: dict[str, Decimal] = {}
        for position in positions:
            usage[position.sleeve_id] = (
                usage.get(position.sleeve_id, Decimal("0")) + position.effective_risk_usd
            )
        for intent in pending_intents or ():
            usage[intent.sleeve_id] = (
                usage.get(intent.sleeve_id, Decimal("0")) + intent.risk_amount_usd
            )
        return usage

    def validate_new_intent(
        self,
        intent: IntentRiskRequest,
        sleeve: SleeveRead,
        profile_mode: ProfileMode,
        *,
        positions: Sequence[SleevePositionSnapshot] = (),
        pending_intents: Sequence[IntentRiskRequest] = (),
    ) -> SleeveGateResult:
        """Return whether a new DealIntent may enter the sleeve."""
        status_block = self._status_block_reason(sleeve.status, profile_mode)
        if status_block is not None:
            return SleeveGateResult(allowed=False, reason=status_block)

        used = self.risk_usage_by_sleeve(positions, pending_intents).get(
            sleeve.id,
            Decimal("0"),
        )
        projected = used + intent.risk_amount_usd
        if projected > sleeve.risk_budget:
            return SleeveGateResult(
                allowed=False,
                reason=(
                    f"sleeve {sleeve.id!r} risk budget exhausted: "
                    f"used={used}, request={intent.risk_amount_usd}, "
                    f"budget={sleeve.risk_budget}"
                ),
            )

        return SleeveGateResult(allowed=True, reason="within sleeve budget and status")

    def validate_compliance_access(
        self,
        request: ComplianceIntentRequest,
    ) -> SleeveGateResult:
        """ComplianceAccessLayer gate — required before creating a new DealIntent."""
        result = check_instrument_access(
            request.instrument_id,
            request.instrument_category,
            request.profile,
        )
        return SleeveGateResult(allowed=result.allowed, reason=result.reason)

    def validate_new_intent_with_compliance(
        self,
        intent: IntentRiskRequest,
        sleeve: SleeveRead,
        profile: ProfileBase,
        *,
        positions: Sequence[SleevePositionSnapshot] = (),
        pending_intents: Sequence[IntentRiskRequest] = (),
    ) -> SleeveGateResult:
        """Run compliance access then sleeve budget/status gates."""
        if intent.instrument_id is not None and intent.instrument_category is not None:
            compliance = self.validate_compliance_access(
                ComplianceIntentRequest(
                    instrument_id=intent.instrument_id,
                    instrument_category=intent.instrument_category,
                    profile=profile,
                )
            )
            if not compliance.allowed:
                return compliance

        return self.validate_new_intent(
            intent,
            sleeve,
            profile.mode,
            positions=positions,
            pending_intents=pending_intents,
        )

    def basket_allocation_targets(
        self,
        basket: CustomBasketSnapshot,
        *,
        sleeve_target_capital_usd: Decimal | None = None,
    ) -> tuple[BasketInstrumentTarget, ...]:
        """Derive per-instrument target capital from basket weights within sleeve context."""
        base_capital = (
            sleeve_target_capital_usd
            if sleeve_target_capital_usd is not None
            else self.total_capital_usd
        )
        targets: list[BasketInstrumentTarget] = []
        for item in basket.items:
            target_usd = (base_capital * item.weight_pct / Decimal("100")).quantize(
                Decimal("0.01")
            )
            targets.append(
                BasketInstrumentTarget(
                    basket_id=basket.basket_id,
                    basket_name=basket.name,
                    sleeve_id=basket.sleeve_id,
                    instrument_id=item.instrument_id,
                    weight_pct=item.weight_pct,
                    target_capital_usd=target_usd,
                )
            )
        return tuple(targets)

    def baskets_for_sleeve(
        self,
        sleeve_id: str,
        baskets: Sequence[CustomBasketSnapshot],
        *,
        sleeve_target_capital_usd: Decimal | None = None,
    ) -> tuple[BasketInstrumentTarget, ...]:
        """Collect basket weight targets linked to a sleeve (analytics/grouping context)."""
        linked = [b for b in baskets if b.sleeve_id == sleeve_id]
        rows: list[BasketInstrumentTarget] = []
        for basket in linked:
            rows.extend(
                self.basket_allocation_targets(
                    basket,
                    sleeve_target_capital_usd=sleeve_target_capital_usd,
                )
            )
        return tuple(rows)

    def rebalance(
        self,
        profile_id: str,
        sleeves: Sequence[SleeveRead],
        positions: Sequence[SleevePositionSnapshot],
    ) -> RebalancePlan:
        """Compare actual vs target sleeve weights; return adjustment plan only."""
        deployed_by_sleeve: dict[str, Decimal] = {}
        for position in positions:
            deployed_by_sleeve[position.sleeve_id] = (
                deployed_by_sleeve.get(position.sleeve_id, Decimal("0"))
                + position.market_value_usd
            )

        total_deployed = sum(deployed_by_sleeve.values(), Decimal("0"))
        adjustments: list[RebalanceAdjustment] = []

        for sleeve in sleeves:
            current_usd = deployed_by_sleeve.get(sleeve.id, Decimal("0"))
            target_usd = self._target_capital(sleeve.capital_allocation_pct)
            delta_usd = target_usd - current_usd
            current_pct = self._pct_of_capital(current_usd)
            action = self._rebalance_action(delta_usd)

            adjustments.append(
                RebalanceAdjustment(
                    sleeve_id=sleeve.id,
                    sleeve_name=sleeve.name,
                    current_pct=current_pct,
                    target_pct=sleeve.capital_allocation_pct,
                    current_usd=current_usd,
                    target_usd=target_usd,
                    delta_usd=delta_usd,
                    action=action,
                )
            )

        return RebalancePlan(
            profile_id=profile_id,
            total_capital_usd=self.total_capital_usd,
            total_deployed_usd=total_deployed,
            adjustments=tuple(adjustments),
            requires_deal_intent=True,
        )

    def risk_budget_allocation(
        self,
        sleeves: Sequence[SleeveRead],
        *,
        total_var_budget_usd: Decimal | None = None,
        strategies_by_sleeve: Mapping[str, Sequence[Strategy]] | None = None,
        regime: str,
        regime_confidence: float = 0.5,
        replay_records: Sequence[Any] | None = None,
    ) -> RiskBudgetAllocation:
        """Distribute profile VaR-equivalent risk budget by regime and replay history."""
        budget = (
            total_var_budget_usd
            if total_var_budget_usd is not None
            else sum((sleeve.risk_budget for sleeve in sleeves), Decimal("0"))
        )
        return risk_budget_allocation(
            total_var_budget_usd=budget,
            sleeves=sleeves,
            strategies_by_sleeve=strategies_by_sleeve,
            regime=regime,
            regime_confidence=regime_confidence,
            replay_records=replay_records,
        )

    def rebalance_risk_budget(
        self,
        profile_id: str,
        sleeves: Sequence[SleeveRead],
        *,
        total_var_budget_usd: Decimal | None = None,
        strategies_by_sleeve: Mapping[str, Sequence[Strategy]] | None = None,
        regime: str,
        regime_confidence: float = 0.5,
        replay_records: Sequence[Any] | None = None,
    ) -> RiskBudgetRebalancePlan:
        """Propose risk budget redistribution — plan only, not auto-executed."""
        allocation = self.risk_budget_allocation(
            sleeves,
            total_var_budget_usd=total_var_budget_usd,
            strategies_by_sleeve=strategies_by_sleeve,
            regime=regime,
            regime_confidence=regime_confidence,
            replay_records=replay_records,
        )
        return build_risk_budget_rebalance_plan(
            profile_id=profile_id,
            sleeves=sleeves,
            allocation=allocation,
        )

    def _allocation_row(
        self,
        sleeve: SleeveRead,
        risk_used_usd: Decimal,
    ) -> SleeveCapitalAllocation:
        remaining = max(Decimal("0"), sleeve.risk_budget - risk_used_usd)
        return SleeveCapitalAllocation(
            sleeve_id=sleeve.id,
            name=sleeve.name,
            category=sleeve.category,
            status=sleeve.status,
            allocation_pct=sleeve.capital_allocation_pct,
            target_capital_usd=self._target_capital(sleeve.capital_allocation_pct),
            risk_budget=sleeve.risk_budget,
            risk_used_usd=risk_used_usd,
            risk_remaining_usd=remaining,
        )

    def _target_capital(self, allocation_pct: Decimal) -> Decimal:
        return (self.total_capital_usd * allocation_pct / Decimal("100")).quantize(
            Decimal("0.01")
        )

    def _pct_of_capital(self, usd: Decimal) -> Decimal:
        if self.total_capital_usd <= 0:
            return Decimal("0")
        return (usd / self.total_capital_usd * Decimal("100")).quantize(Decimal("0.01"))

    @staticmethod
    def _rebalance_action(delta_usd: Decimal) -> RebalanceAction:
        if abs(delta_usd) <= _REBALANCE_HOLD_TOLERANCE_USD:
            return RebalanceAction.HOLD
        if delta_usd > 0:
            return RebalanceAction.INCREASE
        return RebalanceAction.DECREASE

    @staticmethod
    def _status_block_reason(status: SleeveStatus, profile_mode: ProfileMode) -> str | None:
        if status == SleeveStatus.FROZEN:
            return f"sleeve is {SleeveStatus.FROZEN.value}; new intents blocked"

        if status == SleeveStatus.EXPERIMENTAL and profile_mode != ProfileMode.PAPER:
            return (
                f"sleeve is {SleeveStatus.EXPERIMENTAL.value}; "
                "only allowed in paper mode regardless of profile.mode"
            )

        return None
