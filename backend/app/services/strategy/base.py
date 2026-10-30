"""Base strategy helpers — sleeve scope, draft intents, category gating."""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from app.domain.deal_intent import DealIntentCreate
from app.domain.deal_intent_enums import (
    DealIntentDirection,
    DealIntentStatus,
    RiskTag,
    TimeInForce,
    TriggerType,
)
from app.domain.enums import AssetCategory, Strategy

from app.services.strategy.types import InstrumentSnapshot, StrategyMarketContext


class BaseStrategy(ABC):
    """Shared logic: sleeve-only scope, category gate, draft-only output."""

    strategy: Strategy
    allowed_sleeve_categories: frozenset[AssetCategory]

    def analyze(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        if not self._sleeve_allowed(market_context):
            return None
        if not market_context.session_active and market_context.asset_class == "equity":
            return None
        return self._analyze_sleeve(market_context)

    @abstractmethod
    def _analyze_sleeve(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        raise NotImplementedError

    def _sleeve_allowed(self, market_context: StrategyMarketContext) -> bool:
        return market_context.sleeve.category in self.allowed_sleeve_categories

    def _eligible_instruments(
        self,
        market_context: StrategyMarketContext,
    ) -> tuple[InstrumentSnapshot, ...]:
        locked = market_context.news_locked_instrument_ids
        sleeve_category = market_context.sleeve.category
        return tuple(
            item
            for item in market_context.sleeve.instruments
            if item.instrument_id not in locked and item.category == sleeve_category
        )

    def _draft_intent(
        self,
        *,
        market_context: StrategyMarketContext,
        instrument: InstrumentSnapshot,
        direction: DealIntentDirection,
        entry_reason: str,
        required_confidence: float,
        risk_tag: RiskTag,
        trigger_type: TriggerType = TriggerType.LIMIT,
        target_price: Decimal | None = None,
        exit_logic: dict | None = None,
    ) -> DealIntentCreate:
        return DealIntentCreate(
            instrument_id=instrument.instrument_id,
            sleeve_id=market_context.sleeve.sleeve_id,
            direction=direction,
            target_price=target_price or instrument.last_price,
            entry_reason=entry_reason,
            strategy=self.strategy,
            required_confidence=required_confidence,
            max_slippage_bps=50 if market_context.asset_class == "crypto" else 25,
            max_spread_bps=int(instrument.spread_bps) + 10,
            time_in_force=TimeInForce.GTC if market_context.asset_class == "crypto" else TimeInForce.DAY,
            trigger_type=trigger_type,
            exit_logic=exit_logic or {},
            approval_threshold=Decimal("0.70"),
            risk_tag=risk_tag,
            status=DealIntentStatus.DRAFT,
        )
