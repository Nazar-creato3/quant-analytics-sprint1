"""StressHarness domain types (Prompt 27)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.services.scenario.types import AffectedSleeve, ScenarioName, ScenarioResult


@dataclass(frozen=True, slots=True)
class CustomScenarioRequest:
    """Parameterized stress scenario — no code changes required."""

    scenario: ScenarioName
    shock_strength: float
    target_instrument_id: int | None = None
    target_sector: str | None = None


@dataclass(frozen=True, slots=True)
class ScenarioImpactSummary:
    """Per-scenario impact row in a stress report."""

    scenario_name: ScenarioName
    shock_strength: float
    estimated_pnl_impact: float
    estimated_pnl_usd: float
    portfolio_variance_delta: float
    affected_sleeves: tuple[AffectedSleeve, ...]


@dataclass(frozen=True, slots=True)
class PositionReview:
    """Position flagged because stress loss exceeds sleeve risk budget."""

    instrument_id: int
    sleeve_id: str
    weight: float
    scenario_name: ScenarioName
    stressed_loss_fraction: float
    stressed_loss_usd: float
    sleeve_risk_budget_usd: float
    exceeds_budget: bool
    reason: str


@dataclass(frozen=True, slots=True)
class StressReport:
    """Unified on-demand stress test output."""

    profile_id: str
    generated_at: datetime
    portfolio_value_usd: float
    scenario_results: tuple[ScenarioImpactSummary, ...]
    worst_scenario: ScenarioImpactSummary
    max_loss_fraction: float
    max_loss_usd: float
    positions_to_review: tuple[PositionReview, ...]
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "generated_at": self.generated_at.isoformat(),
            "portfolio_value_usd": self.portfolio_value_usd,
            "max_loss_fraction": self.max_loss_fraction,
            "max_loss_usd": self.max_loss_usd,
            "worst_scenario": _scenario_summary_dict(self.worst_scenario),
            "scenario_results": [_scenario_summary_dict(row) for row in self.scenario_results],
            "positions_to_review": [
                {
                    "instrument_id": row.instrument_id,
                    "sleeve_id": row.sleeve_id,
                    "weight": row.weight,
                    "scenario_name": row.scenario_name.value,
                    "stressed_loss_fraction": row.stressed_loss_fraction,
                    "stressed_loss_usd": row.stressed_loss_usd,
                    "sleeve_risk_budget_usd": row.sleeve_risk_budget_usd,
                    "exceeds_budget": row.exceeds_budget,
                    "reason": row.reason,
                }
                for row in self.positions_to_review
            ],
            "metadata": self.metadata,
        }


def _scenario_summary_dict(row: ScenarioImpactSummary) -> dict[str, object]:
    return {
        "scenario_name": row.scenario_name.value,
        "shock_strength": row.shock_strength,
        "estimated_pnl_impact": row.estimated_pnl_impact,
        "estimated_pnl_usd": row.estimated_pnl_usd,
        "portfolio_variance_delta": row.portfolio_variance_delta,
        "affected_sleeves": [
            {
                "sleeve_id": sleeve.sleeve_id,
                "pnl_impact": sleeve.pnl_impact,
                "contribution_pct": sleeve.contribution_pct,
            }
            for sleeve in row.affected_sleeves
        ],
    }


def summarize_scenario(
    result: ScenarioResult,
    *,
    portfolio_value_usd: float,
) -> ScenarioImpactSummary:
    """Convert a ScenarioResult into a report row with USD amounts."""
    return ScenarioImpactSummary(
        scenario_name=result.scenario_name,
        shock_strength=result.shock_strength,
        estimated_pnl_impact=result.estimated_pnl_impact,
        estimated_pnl_usd=result.estimated_pnl_impact * portfolio_value_usd,
        portfolio_variance_delta=result.portfolio_variance_delta,
        affected_sleeves=result.affected_sleeves,
    )


def build_position_reviews(
    scenario_results: tuple[ScenarioResult, ...],
    *,
    portfolio_value_usd: float,
    sleeve_risk_budgets: dict[str, Decimal],
) -> tuple[PositionReview, ...]:
    """Flag instruments whose stressed loss exceeds sleeve risk budget."""
    flagged: dict[tuple[int, ScenarioName], PositionReview] = {}

    for result in scenario_results:
        for instrument in result.affected_instruments:
            loss_fraction = abs(min(0.0, instrument.pnl_impact))
            if loss_fraction <= 0.0:
                continue
            loss_usd = loss_fraction * portfolio_value_usd
            budget = float(sleeve_risk_budgets.get(instrument.sleeve_id, Decimal("0")))
            if budget <= 0.0:
                continue
            if loss_usd <= budget:
                continue

            key = (instrument.instrument_id, result.scenario_name)
            review = PositionReview(
                instrument_id=instrument.instrument_id,
                sleeve_id=instrument.sleeve_id,
                weight=instrument.weight,
                scenario_name=result.scenario_name,
                stressed_loss_fraction=loss_fraction,
                stressed_loss_usd=loss_usd,
                sleeve_risk_budget_usd=budget,
                exceeds_budget=True,
                reason=(
                    f"Stress loss ${loss_usd:,.0f} on {result.scenario_name.value} "
                    f"exceeds sleeve {instrument.sleeve_id!r} risk budget ${budget:,.0f}"
                ),
            )
            existing = flagged.get(key)
            if existing is None or review.stressed_loss_usd > existing.stressed_loss_usd:
                flagged[key] = review

    return tuple(sorted(flagged.values(), key=lambda row: -row.stressed_loss_usd))
