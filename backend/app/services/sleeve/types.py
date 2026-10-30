"""Types for SleeveEngine — allocation, gating, and rebalance plans."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.domain.enums import AssetCategory, SleeveStatus, Strategy
from app.domain.profile import ProfileBase


class RebalanceAction(str, Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class SleevePositionSnapshot:
    """Open position attributed to a sleeve (synthetic or live)."""

    sleeve_id: str
    market_value_usd: Decimal
    risk_usd: Decimal | None = None

    @property
    def effective_risk_usd(self) -> Decimal:
        return self.risk_usd if self.risk_usd is not None else self.market_value_usd


@dataclass(frozen=True, slots=True)
class IntentRiskRequest:
    """Minimal DealIntent slice for sleeve budget and status checks."""

    sleeve_id: str
    risk_amount_usd: Decimal
    instrument_id: int | None = None
    instrument_category: AssetCategory | None = None


@dataclass(frozen=True, slots=True)
class ComplianceIntentRequest:
    """Instrument/category slice for compliance access checks."""

    instrument_id: int
    instrument_category: AssetCategory
    profile: ProfileBase


@dataclass(frozen=True, slots=True)
class SleeveCapitalAllocation:
    sleeve_id: str
    name: str
    category: AssetCategory
    status: SleeveStatus
    allocation_pct: Decimal
    target_capital_usd: Decimal
    risk_budget: Decimal
    risk_used_usd: Decimal
    risk_remaining_usd: Decimal


@dataclass(frozen=True, slots=True)
class SleeveGateResult:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class RebalanceAdjustment:
    sleeve_id: str
    sleeve_name: str
    current_pct: Decimal
    target_pct: Decimal
    current_usd: Decimal
    target_usd: Decimal
    delta_usd: Decimal
    action: RebalanceAction


@dataclass(frozen=True, slots=True)
class RebalancePlan:
    """Suggested sleeve weight corrections — not auto-executed."""

    profile_id: str
    total_capital_usd: Decimal
    total_deployed_usd: Decimal
    adjustments: tuple[RebalanceAdjustment, ...]
    requires_deal_intent: bool = True


@dataclass(frozen=True, slots=True)
class CustomBasketItemSnapshot:
    """Weighted instrument inside a custom basket (analytics only)."""

    instrument_id: int
    weight_pct: Decimal


@dataclass(frozen=True, slots=True)
class CustomBasketSnapshot:
    """Custom basket attached to optional sleeve context — does not replace sleeve allocation."""

    basket_id: str
    name: str
    sleeve_id: str | None
    items: tuple[CustomBasketItemSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class BasketInstrumentTarget:
    """Per-instrument target capital derived from basket weights within sleeve context."""

    basket_id: str
    basket_name: str
    sleeve_id: str | None
    instrument_id: int
    weight_pct: Decimal
    target_capital_usd: Decimal


@dataclass(frozen=True, slots=True)
class StrategyRiskBudgetTarget:
    """Per-strategy VaR-equivalent budget within a sleeve."""

    sleeve_id: str
    strategy: Strategy
    target_var_budget_usd: Decimal
    regime_multiplier: float = 1.0
    replay_effectiveness: float = 1.0


@dataclass(frozen=True, slots=True)
class RiskBudgetAllocation:
    """Proposed VaR-equivalent risk budget split — not auto-applied."""

    regime: str
    regime_confidence: float
    total_var_budget_usd: Decimal
    sleeve_var_budget_usd: dict[str, Decimal]
    strategy_targets: tuple[StrategyRiskBudgetTarget, ...] = ()


@dataclass(frozen=True, slots=True)
class RiskBudgetRebalanceAdjustment:
    sleeve_id: str
    sleeve_name: str
    current_var_budget_usd: Decimal
    target_var_budget_usd: Decimal
    delta_var_budget_usd: Decimal


@dataclass(frozen=True, slots=True)
class RiskBudgetRebalancePlan:
    """Suggested risk budget corrections — requires separate DealIntent to apply."""

    profile_id: str
    regime: str
    regime_confidence: float
    total_var_budget_usd: Decimal
    allocation: RiskBudgetAllocation
    adjustments: tuple[RiskBudgetRebalanceAdjustment, ...]
    requires_deal_intent: bool = True
