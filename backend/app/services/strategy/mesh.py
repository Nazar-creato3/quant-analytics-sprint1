"""StrategyMesh — plugin registry for pluggable trading strategies."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.deal_intent import DealIntentCreate
from app.domain.enums import AssetCategory, Strategy
from app.domain.profile import ProfileBase
from app.services.compliance import check_instrument_access
from app.services.equity.intent_enrichment import enrich_intent_with_event_proximity
from app.services.sleeve import ComplianceIntentRequest, SleeveEngine, SleeveGateResult
from app.services.strategy.strategies import (
    BreakoutStrategy,
    GridStrategy,
    HedgeStrategy,
    IncomeStrategy,
    MeanReversionStrategy,
    RotationStrategy,
    TrendStrategy,
    VolatilityHarvestingStrategy,
)
from app.services.strategy.types import StrategyMarketContext


class StrategyRegistrationError(ValueError):
    """Raised when a strategy cannot be registered in the mesh."""


@dataclass(frozen=True, slots=True)
class StrategyIntentProposal:
    """Draft intent candidate with compliance gate outcome."""

    intent: DealIntentCreate | None
    compliance: SleeveGateResult
    blocked: bool


class StrategyMesh:
    """Registry and dispatcher for strategy plugins."""

    def __init__(
        self,
        strategies: Iterable[Any] | None = None,
        *,
        sleeve_engine: SleeveEngine | None = None,
    ) -> None:
        self._strategies: dict[Strategy, Any] = {}
        self._sleeve_engine = sleeve_engine
        if strategies is not None:
            for strategy in strategies:
                self.register(strategy)

    @classmethod
    def default(cls) -> StrategyMesh:
        """Mesh pre-loaded with all built-in strategies."""
        return cls(
            [
                GridStrategy(),
                TrendStrategy(),
                MeanReversionStrategy(),
                BreakoutStrategy(),
                HedgeStrategy(),
                IncomeStrategy(),
                RotationStrategy(),
                VolatilityHarvestingStrategy(),
            ]
        )

    def register(self, strategy: Any) -> None:
        key = strategy.strategy
        if key in self._strategies:
            raise StrategyRegistrationError(f"strategy {key.value!r} already registered")
        self._strategies[key] = strategy

    def get(self, strategy_type: Strategy) -> Any | None:
        return self._strategies.get(strategy_type)

    def analyze(
        self,
        strategy_type: Strategy,
        market_context: StrategyMarketContext,
    ) -> DealIntentCreate | None:
        """Run a registered strategy against sleeve-scoped market context."""
        strategy = self.get(strategy_type)
        if strategy is None:
            return None
        return strategy.analyze(market_context)

    def analyze_all(
        self,
        market_context: StrategyMarketContext,
    ) -> dict[Strategy, DealIntentCreate | None]:
        """Run every registered strategy; useful for scanning a sleeve."""
        return {
            strategy_type: strategy.analyze(market_context)
            for strategy_type, strategy in self._strategies.items()
        }

    def run_compliance_guard(
        self,
        profile: ProfileBase,
        instrument_id: int,
        instrument_category: AssetCategory,
    ) -> SleeveGateResult:
        """Compliance gate — required before intent leaves draft pipeline."""
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
        strategy_key: Strategy,
        profile: ProfileBase,
        market_context: StrategyMarketContext | Any,
        *,
        instrument_id: int,
        instrument_category: AssetCategory,
    ) -> StrategyIntentProposal:
        """Run strategy analysis only after compliance access passes."""
        compliance = self.run_compliance_guard(profile, instrument_id, instrument_category)
        if not compliance.allowed:
            return StrategyIntentProposal(intent=None, compliance=compliance, blocked=True)

        strategy = self._strategies.get(strategy_key)
        if strategy is None:
            return StrategyIntentProposal(
                intent=None,
                compliance=compliance,
                blocked=True,
            )

        intent = strategy.analyze(market_context)
        if intent is not None and market_context.event_proximity is not None:
            intent = enrich_intent_with_event_proximity(intent, market_context.event_proximity)
        return StrategyIntentProposal(intent=intent, compliance=compliance, blocked=False)

    @property
    def registered(self) -> Mapping[Strategy, Any]:
        return dict(self._strategies)

    def __len__(self) -> int:
        return len(self._strategies)

    def __contains__(self, strategy_type: Strategy) -> bool:
        return strategy_type in self._strategies
