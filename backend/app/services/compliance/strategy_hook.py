"""Strategy compliance hook — integration point until StrategyMesh (PROMPT 6) merges."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.domain.deal_intent import DealIntentCreate
from app.domain.enums import AssetCategory, Strategy
from app.domain.profile import ProfileBase
from app.services.compliance.access_layer import check_instrument_access
from app.services.sleeve.types import ComplianceIntentRequest, SleeveGateResult

if TYPE_CHECKING:
    from app.services.sleeve.engine import SleeveEngine


@dataclass(frozen=True, slots=True)
class StrategyComplianceProposal:
    intent: DealIntentCreate | None
    compliance: SleeveGateResult
    blocked: bool


class ComplianceStrategyHook:
    """Compliance guard strategies call before emitting draft DealIntents."""

    def __init__(self, *, sleeve_engine: "SleeveEngine | None" = None) -> None:
        self._sleeve_engine = sleeve_engine

    def run_compliance_guard(
        self,
        profile: ProfileBase,
        instrument_id: int,
        instrument_category: AssetCategory,
    ) -> SleeveGateResult:
        if self._sleeve_engine is not None:
            return self._sleeve_engine.validate_compliance_access(
                ComplianceIntentRequest(
                    instrument_id=instrument_id,
                    instrument_category=instrument_category,
                    profile=profile,
                )
            )
        result = check_instrument_access(instrument_id, instrument_category, profile)
        return SleeveGateResult(allowed=result.allowed, reason=result.reason)

    def propose_intent(
        self,
        profile: ProfileBase,
        instrument_id: int,
        instrument_category: AssetCategory,
        analyze: Any,
        market_context: Any,
    ) -> StrategyComplianceProposal:
        compliance = self.run_compliance_guard(profile, instrument_id, instrument_category)
        if not compliance.allowed:
            return StrategyComplianceProposal(intent=None, compliance=compliance, blocked=True)
        intent = analyze(market_context)
        return StrategyComplianceProposal(intent=intent, compliance=compliance, blocked=False)
