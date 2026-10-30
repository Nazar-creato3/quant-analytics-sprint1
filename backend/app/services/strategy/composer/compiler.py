"""Compile declarative composer configs into StrategyMesh parameters."""
from __future__ import annotations

from typing import Any

from app.services.strategy.composer.models import (
    REGIME_ALIASES,
    ComposerConfig,
    ComposerOutcome,
    ComposerPredicate,
    CompiledOutcome,
    CompiledRule,
    CompiledStrategyConfig,
)
from app.services.strategy.types import GridMode, MarketRegime, StrategyMarketContext


def _normalize_regime_value(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        expanded: list[str] = []
        for item in value:
            expanded.extend(_normalize_regime_value(item))
        return expanded
    alias = REGIME_ALIASES.get(value)
    if alias:
        return list(alias)
    return [value]


def _compile_predicate(predicate: ComposerPredicate) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "field": predicate.field.value,
        "operator": predicate.operator.value,
    }
    if predicate.field.value == "regime":
        if predicate.operator.value == "in" or isinstance(predicate.value, list):
            payload["value"] = _normalize_regime_value(predicate.value)  # type: ignore[arg-type]
        else:
            expanded = _normalize_regime_value(str(predicate.value))
            payload["value"] = expanded[0] if len(expanded) == 1 else expanded
    else:
        payload["value"] = predicate.value
    return payload


def _compile_outcome(outcome: ComposerOutcome) -> CompiledOutcome:
    return CompiledOutcome(
        primary_strategy=outcome.primary_strategy.value,
        grid_mode=outcome.grid_mode.value if outcome.grid_mode else None,
    )


def compile_composer_config(config: ComposerConfig) -> CompiledStrategyConfig:
    """Compile a validated composer config into whitelisted strategy parameters."""
    outcome_map = {outcome.id: outcome for outcome in config.outcomes}
    rules: list[CompiledRule] = []

    for branch in config.branches:
        then_outcome = outcome_map[branch.then_outcome_id]
        else_outcome = (
            _compile_outcome(outcome_map[branch.else_outcome_id])
            if branch.else_outcome_id
            else None
        )
        rules.append(
            CompiledRule(
                branch_id=branch.id,
                logic=branch.condition.logic,
                conditions=[_compile_predicate(p) for p in branch.condition.predicates],
                then=_compile_outcome(then_outcome),
                else_outcome=else_outcome,
                else_branch_id=branch.else_branch_id,
            )
        )

    default = _compile_outcome(outcome_map[config.default_outcome_id])
    return CompiledStrategyConfig(
        version=config.version,
        name=config.name,
        rules=rules,
        default=default,
    )


def _predicate_matches(context: StrategyMarketContext, predicate: dict[str, Any]) -> bool:
    field = predicate["field"]
    operator = predicate["operator"]
    expected = predicate["value"]

    if field == "volatility_percentile":
        actual = context.volatility_percentile
    elif field == "volatility":
        instruments = context.sleeve.instruments
        actual = max((item.volatility for item in instruments), default=0.0)
    elif field == "regime":
        actual = context.regime.value
        if operator == "in" or isinstance(expected, list):
            values = expected if isinstance(expected, list) else [expected]
            expanded = _normalize_regime_value(values)  # type: ignore[arg-type]
            return actual in expanded
        if operator == "eq":
            expanded = _normalize_regime_value(str(expected))
            return actual in expanded
        if operator == "neq":
            expanded = _normalize_regime_value(str(expected))
            return actual not in expanded
        raise ValueError(f"unsupported regime operator: {operator}")
    elif field == "microstructure_score":
        actual = context.microstructure_score
    elif field == "session_active":
        actual = context.session_active
        if operator == "eq":
            return actual == expected
        if operator == "neq":
            return actual != expected
        raise ValueError(f"unsupported session_active operator: {operator}")
    else:
        raise ValueError(f"unknown field: {field}")

    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    if operator == "eq":
        return actual == expected
    if operator == "neq":
        return actual != expected
    raise ValueError(f"unsupported operator: {operator}")


def _conditions_match(
    context: StrategyMarketContext,
    conditions: list[dict[str, Any]],
    logic: str,
) -> bool:
    if not conditions:
        return True
    results = [_predicate_matches(context, cond) for cond in conditions]
    if logic == "and":
        return all(results)
    return any(results)


def resolve_from_root(
    context: StrategyMarketContext,
    compiled: CompiledStrategyConfig,
    *,
    root_branch_id: str,
) -> CompiledOutcome:
    """Evaluate compiled rules starting at explicit root branch."""
    rule_map = {rule.branch_id: rule for rule in compiled.rules}
    current_id: str | None = root_branch_id
    visited: set[str] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        rule = rule_map.get(current_id)
        if rule is None:
            break
        if _conditions_match(context, rule.conditions, rule.logic):
            return rule.then
        if rule.else_outcome is not None:
            return rule.else_outcome
        current_id = rule.else_branch_id

    return compiled.default


def apply_outcome_to_context(
    context: StrategyMarketContext,
    outcome: CompiledOutcome,
) -> StrategyMarketContext:
    """Return a new context with grid_mode applied from compiled outcome."""
    grid_mode = context.grid_mode
    if outcome.grid_mode:
        grid_mode = GridMode(outcome.grid_mode)
    return StrategyMarketContext(
        sleeve=context.sleeve,
        regime=context.regime,
        session_active=context.session_active,
        microstructure_score=context.microstructure_score,
        volatility_percentile=context.volatility_percentile,
        asset_class=context.asset_class,
        grid_mode=grid_mode,
        news_locked_instrument_ids=context.news_locked_instrument_ids,
    )
