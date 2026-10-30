"""Approval policy domain types — decisions and market context."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from app.domain.enums import AssetCategory, SleeveStatus


class PolicyState(str, Enum):
    AUTO_APPROVE = "auto_approve"
    CONDITIONAL_APPROVE = "conditional_approve"
    HOLD_FOR_REVIEW = "hold_for_review"
    REJECT_HARD = "reject_hard"
    FREEZE_SLEEVE = "freeze_sleeve"
    KILL_SESSION = "kill_session"


TERMINAL_POLICY_STATES = frozenset(
    {
        PolicyState.AUTO_APPROVE,
        PolicyState.CONDITIONAL_APPROVE,
        PolicyState.REJECT_HARD,
        PolicyState.KILL_SESSION,
    }
)


@dataclass(frozen=True, slots=True)
class MarketContext:
    """Read-model inputs from market data and news layers."""

    instrument_volatility: float = 0.0
    instrument_spread_bps: float = 0.0
    instrument_category: AssetCategory | None = None
    max_correlation_with_portfolio: float = 0.0
    news_locked_instrument_ids: frozenset[int] = field(default_factory=frozenset)
    event_proximity_locked_instrument_ids: frozenset[int] = field(default_factory=frozenset)
    liquidity_drought_instrument_ids: frozenset[int] = field(default_factory=frozenset)
    active_lock_instrument_ids: frozenset[int] = field(default_factory=frozenset)
    active_lock_sleeve_ids: frozenset[str] = field(default_factory=frozenset)
    market_regime: str = "unknown"
    session_killed: bool = False
    profile_drawdown_pct: float = 0.0
    profile_daily_loss_abs: Decimal = Decimal("0")
    sleeve_status: SleeveStatus = SleeveStatus.ACTIVE
    sleeve_risk_budget_remaining: Decimal | None = None
    freeze_sleeve_requested: bool = False
    dominant_regime: str = "unknown"
    regime_confidence: float = 0.0
    forecast_confidence: float = 0.0
    forecast_composite_risk_score: float = 0.0
    tail_risk_score: float = 0.0
    risk_engine_breach_count: int = 0
    risk_flags: tuple[str, ...] = field(default_factory=tuple)
    proposed_delta_var: float = 0.0
    remaining_risk_budget_var: float | None = None
    marginal_risk_computed: bool = False

    def __post_init__(self) -> None:
        if self.instrument_volatility < 0:
            raise ValueError("instrument_volatility must be non-negative")
        if self.instrument_spread_bps < 0:
            raise ValueError("instrument_spread_bps must be non-negative")
        if not 0.0 <= self.max_correlation_with_portfolio <= 1.0:
            raise ValueError("max_correlation_with_portfolio must be in [0, 1]")
        if not 0.0 <= self.regime_confidence <= 1.0:
            raise ValueError("regime_confidence must be in [0, 1]")
        if not 0.0 <= self.forecast_confidence <= 1.0:
            raise ValueError("forecast_confidence must be in [0, 1]")
        if not 0.0 <= self.forecast_composite_risk_score <= 1.0:
            raise ValueError("forecast_composite_risk_score must be in [0, 1]")
        if not 0.0 <= self.tail_risk_score <= 1.0:
            raise ValueError("tail_risk_score must be in [0, 1]")
        if self.risk_engine_breach_count < 0:
            raise ValueError("risk_engine_breach_count must be non-negative")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    state: PolicyState
    reason: str
    risk_score: float
    conditions_met: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reason must be non-empty")
        if not 0.0 <= self.risk_score <= 1.0:
            raise ValueError("risk_score must be in [0, 1]")

    @property
    def is_approvable(self) -> bool:
        return self.state in {PolicyState.AUTO_APPROVE, PolicyState.CONDITIONAL_APPROVE}

    def to_audit_details(self) -> dict[str, Any]:
        return {
            "policy_state": self.state.value,
            "reason": self.reason,
            "risk_score": self.risk_score,
            "conditions_met": self.conditions_met,
            "metadata": self.metadata,
        }
