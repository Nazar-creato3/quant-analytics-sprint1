"""Stress scenarios and shock analysis for Terminal Quant."""
from __future__ import annotations

from app.services.terminal_platform.quant.models import (
    Portfolio,
    ShockSpec,
    StressResult,
    StressScenario,
)

# Built-in named scenarios (fractional return shocks).
BUILTIN_SCENARIOS: dict[str, StressScenario] = {
    "equity_crash": StressScenario(
        name="equity_crash",
        description="Broad equity -20% shock",
        asset_shocks={},  # filled per-portfolio as default shock
    ),
    "rate_shock": StressScenario(
        name="rate_shock",
        description="Rates up / duration assets -8%",
        asset_shocks={},
    ),
    "liquidity_drought": StressScenario(
        name="liquidity_drought",
        description="Liquidity crunch -12%",
        asset_shocks={},
    ),
}

_DEFAULT_SHOCKS = {
    "equity_crash": -0.20,
    "rate_shock": -0.08,
    "liquidity_drought": -0.12,
}


def stress_scenario(
    portfolio: Portfolio,
    scenario: StressScenario | str,
    *,
    default_shock: float | None = None,
) -> StressResult:
    """Apply a named/custom scenario shock vector to portfolio weights."""
    if isinstance(scenario, str):
        if scenario not in BUILTIN_SCENARIOS and scenario not in _DEFAULT_SHOCKS:
            raise ValueError(f"unknown scenario: {scenario}")
        base = BUILTIN_SCENARIOS.get(scenario)
        shock_value = default_shock if default_shock is not None else _DEFAULT_SHOCKS.get(scenario, -0.10)
        asset_shocks = {
            p.symbol: float(base.asset_shocks.get(p.symbol, shock_value)) if base else float(shock_value)
            for p in portfolio.positions
        }
        scenario_obj = StressScenario(
            name=scenario,
            description=base.description if base else None,
            asset_shocks=asset_shocks,
        )
    else:
        scenario_obj = scenario
        if not scenario_obj.asset_shocks:
            shock_value = default_shock if default_shock is not None else -0.10
            scenario_obj = scenario_obj.model_copy(
                update={
                    "asset_shocks": {p.symbol: shock_value for p in portfolio.positions},
                }
            )

    return _apply_shocks(portfolio, scenario_obj.name, scenario_obj.asset_shocks)


def shock_analysis(
    portfolio: Portfolio,
    shocks: ShockSpec | dict[str, float],
) -> StressResult:
    """Ad-hoc shock analysis (symbol → return shock)."""
    if isinstance(shocks, ShockSpec):
        label = shocks.label
        mapping = shocks.shocks
    else:
        label = "custom"
        mapping = shocks
    return _apply_shocks(portfolio, label, mapping)


def _apply_shocks(
    portfolio: Portfolio,
    name: str,
    shocks: dict[str, float],
) -> StressResult:
    weights = {p.symbol: p.weight for p in portfolio.positions}
    weight_sum = sum(weights.values())
    if abs(weight_sum) < 1e-15:
        raise ValueError("portfolio weights sum to zero")

    contributions: dict[str, float] = {}
    pnl_pct = 0.0
    for symbol, weight in weights.items():
        shock = float(shocks.get(symbol, 0.0))
        contrib = (weight / weight_sum) * shock
        contributions[symbol] = contrib
        pnl_pct += contrib

    return StressResult(
        scenario_name=name,
        portfolio_pnl_pct=float(pnl_pct),
        portfolio_pnl_usd=float(pnl_pct * portfolio.value_usd),
        contribution_by_symbol=contributions,
        metadata={"weight_sum": weight_sum, "n_positions": len(weights)},
    )
