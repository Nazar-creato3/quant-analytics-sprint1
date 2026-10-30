"""Risk budget allocation across sleeves and strategies (Prompt 26).

Distributes profile-level VaR-equivalent risk budget using regime context and
ReplayEngine historical effectiveness — plan only, not auto-executed.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Protocol

from app.domain.enums import AssetCategory, SleeveStatus, Strategy
from app.domain.sleeve import SleeveRead
from app.services.regime.types import MarketRegimeLabel
from app.services.sleeve.types import (
    RiskBudgetAllocation,
    RiskBudgetRebalanceAdjustment,
    RiskBudgetRebalancePlan,
    StrategyRiskBudgetTarget,
)

_BULLISH_TREND = MarketRegimeLabel.BULLISH_TREND.value
_HIGH_VOL_SHOCK = MarketRegimeLabel.HIGH_VOLATILITY_SHOCK.value

_DEFENSIVE_CATEGORIES: frozenset[AssetCategory] = frozenset(
    {
        AssetCategory.DEFENSIVE_SLEEVE,
        AssetCategory.INCOME_SLEEVE,
        AssetCategory.MACRO_HEDGE,
        AssetCategory.RATES_BONDS,
    }
)
_SPECULATIVE_CATEGORIES: frozenset[AssetCategory] = frozenset(
    {
        AssetCategory.SPECULATIVE_SLEEVE,
        AssetCategory.CRYPTO,
    }
)

_BULLISH_STRATEGY_BOOST: dict[Strategy, float] = {
    Strategy.TREND: 1.35,
    Strategy.BREAKOUT: 1.20,
    Strategy.ROTATION: 1.15,
    Strategy.MEAN_REVERSION: 0.85,
    Strategy.GRID: 0.95,
}

_SHOCK_STRATEGY_BOOST: dict[Strategy, float] = {
    Strategy.HEDGE: 1.40,
    Strategy.INCOME: 1.25,
    Strategy.TREND: 0.35,
    Strategy.BREAKOUT: 0.30,
    Strategy.VOLATILITY_HARVESTING: 0.40,
    Strategy.ROTATION: 0.50,
    Strategy.MEAN_REVERSION: 0.70,
    Strategy.GRID: 0.60,
}


class _ReplayRecordLike(Protocol):
    sleeve_id: str
    intent_snapshot: dict[str, Any]
    market_snapshot: dict[str, Any]


def _sleeve_risk_tier(sleeve: SleeveRead) -> str:
    if sleeve.status == SleeveStatus.EXPERIMENTAL:
        return "experimental"
    if sleeve.category in _DEFENSIVE_CATEGORIES:
        return "defensive"
    if sleeve.category in _SPECULATIVE_CATEGORIES:
        return "speculative"
    return "core"


def _regime_sleeve_multiplier(
    tier: str,
    regime: str,
    *,
    regime_confidence: float,
) -> float:
    confidence = max(0.0, min(1.0, regime_confidence))

    if regime == _HIGH_VOL_SHOCK:
        if tier == "defensive":
            return 1.05
        if tier == "core":
            return 0.45
        if tier == "speculative":
            return 0.12
        if tier == "experimental":
            return 0.05
        return 0.40

    if regime == _BULLISH_TREND:
        boost = 1.0 + 0.15 * confidence
        if tier == "defensive":
            return max(0.85, 1.0 - 0.10 * confidence)
        if tier == "speculative":
            return 1.0 + 0.08 * confidence
        if tier == "experimental":
            return 1.0 + 0.05 * confidence
        return boost

    return 1.0


def _strategy_regime_multiplier(
    strategy: Strategy,
    regime: str,
    *,
    regime_confidence: float,
) -> float:
    confidence = max(0.0, min(1.0, regime_confidence))
    table = _BULLISH_STRATEGY_BOOST if regime == _BULLISH_TREND else _SHOCK_STRATEGY_BOOST
    base = table.get(strategy, 1.0)
    if regime == _BULLISH_TREND and confidence >= 0.60:
        if strategy in (Strategy.TREND, Strategy.BREAKOUT, Strategy.ROTATION):
            return base * (1.0 + 0.10 * (confidence - 0.60) / 0.40)
    return base


def _extract_strategy(record: _ReplayRecordLike) -> Strategy | None:
    raw = record.intent_snapshot.get("strategy")
    if raw is None:
        return None
    try:
        return Strategy(str(raw))
    except ValueError:
        return None


def _replay_effectiveness_scores(
    records: Sequence[_ReplayRecordLike],
    *,
    regime: str,
) -> dict[tuple[str, Strategy], float]:
    """Success rate per (sleeve_id, strategy) in the same regime from replay history."""
    totals: dict[tuple[str, Strategy], int] = {}
    successes: dict[tuple[str, Strategy], int] = {}

    for record in records:
        record_regime = str(record.market_snapshot.get("market_regime", "unknown"))
        if record_regime != regime:
            continue
        strategy = _extract_strategy(record)
        if strategy is None:
            continue
        key = (record.sleeve_id, strategy)
        totals[key] = totals.get(key, 0) + 1
        risk_allowed = bool(record.market_snapshot.get("replay_risk_allowed", True))
        approval_allowed = bool(record.market_snapshot.get("replay_approval_allowed", True))
        if risk_allowed and approval_allowed:
            successes[key] = successes.get(key, 0) + 1

    scores: dict[tuple[str, Strategy], float] = {}
    for key, count in totals.items():
        if count <= 0:
            continue
        rate = successes.get(key, 0) / count
        scores[key] = 0.50 + rate
    return scores


def _quantize_usd(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _allocate_proportional(
    total: Decimal,
    weights: Mapping[str, Decimal],
) -> dict[str, Decimal]:
    weight_sum = sum(weights.values(), Decimal("0"))
    if weight_sum <= 0 or total <= 0:
        return {key: Decimal("0.00") for key in weights}

    allocated: dict[str, Decimal] = {}
    running = Decimal("0")
    keys = list(weights.keys())
    for index, key in enumerate(keys):
        if index == len(keys) - 1:
            share = _quantize_usd(total - running)
        else:
            share = _quantize_usd(total * weights[key] / weight_sum)
            running += share
        allocated[key] = share
    return allocated


def risk_budget_allocation(
    *,
    total_var_budget_usd: Decimal,
    sleeves: Sequence[SleeveRead],
    strategies_by_sleeve: Mapping[str, Sequence[Strategy]] | None = None,
    regime: str,
    regime_confidence: float = 0.5,
    replay_records: Sequence[_ReplayRecordLike] | None = None,
) -> RiskBudgetAllocation:
    """Allocate VaR-equivalent risk budget across sleeves and strategies."""
    if total_var_budget_usd < 0:
        raise ValueError("total_var_budget_usd must be non-negative")

    strategies_map = strategies_by_sleeve or {}
    effectiveness = _replay_effectiveness_scores(replay_records or (), regime=regime)

    sleeve_weights: dict[str, Decimal] = {}
    for sleeve in sleeves:
        tier = _sleeve_risk_tier(sleeve)
        regime_mult = _regime_sleeve_multiplier(
            tier,
            regime,
            regime_confidence=regime_confidence,
        )
        base = sleeve.capital_allocation_pct if sleeve.capital_allocation_pct > 0 else Decimal("1")
        sleeve_weights[sleeve.id] = base * Decimal(str(regime_mult))

    sleeve_budgets = _allocate_proportional(total_var_budget_usd, sleeve_weights)

    strategy_targets: list[StrategyRiskBudgetTarget] = []
    for sleeve in sleeves:
        sleeve_budget = sleeve_budgets.get(sleeve.id, Decimal("0"))
        strategies = tuple(strategies_map.get(sleeve.id, ()))
        if not strategies:
            continue

        strat_weights: dict[Strategy, Decimal] = {}
        for strategy in strategies:
            regime_mult = _strategy_regime_multiplier(
                strategy,
                regime,
                regime_confidence=regime_confidence,
            )
            replay_mult = effectiveness.get((sleeve.id, strategy), 1.0)
            strat_weights[strategy] = Decimal(str(regime_mult * replay_mult))

        strat_budgets = _allocate_proportional(sleeve_budget, strat_weights)
        for strategy in strategies:
            strategy_targets.append(
                StrategyRiskBudgetTarget(
                    sleeve_id=sleeve.id,
                    strategy=strategy,
                    target_var_budget_usd=strat_budgets.get(strategy, Decimal("0")),
                    regime_multiplier=_strategy_regime_multiplier(
                        strategy,
                        regime,
                        regime_confidence=regime_confidence,
                    ),
                    replay_effectiveness=effectiveness.get((sleeve.id, strategy), 1.0),
                )
            )

    return RiskBudgetAllocation(
        regime=regime,
        regime_confidence=regime_confidence,
        total_var_budget_usd=total_var_budget_usd,
        sleeve_var_budget_usd=sleeve_budgets,
        strategy_targets=tuple(strategy_targets),
    )


def build_risk_budget_rebalance_plan(
    *,
    profile_id: str,
    sleeves: Sequence[SleeveRead],
    allocation: RiskBudgetAllocation,
) -> RiskBudgetRebalancePlan:
    """Compare current sleeve risk budgets with proposed VaR allocation."""
    adjustments: list[RiskBudgetRebalanceAdjustment] = []
    for sleeve in sleeves:
        current = sleeve.risk_budget
        target = allocation.sleeve_var_budget_usd.get(sleeve.id, Decimal("0"))
        delta = _quantize_usd(target - current)
        adjustments.append(
            RiskBudgetRebalanceAdjustment(
                sleeve_id=sleeve.id,
                sleeve_name=sleeve.name,
                current_var_budget_usd=current,
                target_var_budget_usd=target,
                delta_var_budget_usd=delta,
            )
        )

    return RiskBudgetRebalancePlan(
        profile_id=profile_id,
        regime=allocation.regime,
        regime_confidence=allocation.regime_confidence,
        total_var_budget_usd=allocation.total_var_budget_usd,
        allocation=allocation,
        adjustments=tuple(adjustments),
        requires_deal_intent=True,
    )
