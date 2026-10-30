"""Strategy plugin interface for StrategyMesh."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.deal_intent import DealIntentCreate
from app.domain.enums import Strategy

from app.services.strategy.types import StrategyMarketContext


@runtime_checkable
class IStrategy(Protocol):
    """Pluggable strategy — produces draft DealIntent only, never executes."""

    strategy: Strategy
    allowed_sleeve_categories: frozenset

    def analyze(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        """Return a draft intent for the best opportunity in the sleeve, or None."""
        ...
