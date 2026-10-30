"""StressHarness — on-demand portfolio stress testing (Prompt 27)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.services.scenario.engine import ScenarioEngine
from app.services.scenario.types import PortfolioSnapshot, ScenarioName, ScenarioResult
from app.services.stress_harness.loader import ProfilePortfolioContext, StressHarnessLoader
from app.services.stress_harness.types import (
    CustomScenarioRequest,
    ScenarioImpactSummary,
    StressReport,
    build_position_reviews,
    summarize_scenario,
)


class StressHarness:
    """Run ScenarioEngine scenarios against a live profile portfolio."""

    def __init__(
        self,
        *,
        scenario_engine: ScenarioEngine | None = None,
        loader: StressHarnessLoader | None = None,
    ) -> None:
        self._scenario_engine = scenario_engine or ScenarioEngine()
        self._loader = loader or StressHarnessLoader()

    @property
    def loader(self) -> StressHarnessLoader:
        return self._loader

    def run_all_scenarios(
        self,
        context: ProfilePortfolioContext,
        *,
        target_instrument_id: int | None = None,
        target_sector: str | None = None,
    ) -> StressReport:
        """Run every built-in scenario with default shock strengths."""
        target_instrument_id, target_sector = self._resolve_scenario_targets(
            context.portfolio,
            target_instrument_id=target_instrument_id,
            target_sector=target_sector,
        )
        raw_results = self._scenario_engine.run_all(
            context.portfolio,
            target_instrument_id=target_instrument_id,
            target_sector=target_sector,
        )
        ordered = tuple(raw_results[name] for name in ScenarioName)
        return self._build_report(
            profile_id=context.profile_id,
            portfolio_value_usd=context.portfolio_value_usd,
            sleeve_risk_budgets=context.sleeve_risk_budgets,
            scenario_results=ordered,
            metadata={
                "mode": "all_scenarios",
                "position_count": len(context.portfolio.positions),
            },
        )

    def run_custom_scenario(
        self,
        context: ProfilePortfolioContext,
        request: CustomScenarioRequest,
    ) -> StressReport:
        """Run a single parameterized scenario without code changes."""
        target_instrument_id, target_sector = self._resolve_scenario_targets(
            context.portfolio,
            target_instrument_id=request.target_instrument_id,
            target_sector=request.target_sector,
        )
        result = self._scenario_engine.run(
            request.scenario,
            context.portfolio,
            shock_strength=request.shock_strength,
            target_instrument_id=target_instrument_id,
            target_sector=target_sector,
        )
        return self._build_report(
            profile_id=context.profile_id,
            portfolio_value_usd=context.portfolio_value_usd,
            sleeve_risk_budgets=context.sleeve_risk_budgets,
            scenario_results=(result,),
            metadata={
                "mode": "custom_scenario",
                "position_count": len(context.portfolio.positions),
                "custom_scenario": request.scenario.value,
                "shock_strength": request.shock_strength,
            },
        )

    def run_on_snapshot(
        self,
        *,
        profile_id: str,
        portfolio: PortfolioSnapshot,
        portfolio_value_usd: float,
        sleeve_risk_budgets: dict[str, Decimal],
        scenarios: tuple[ScenarioResult, ...] | None = None,
        target_instrument_id: int | None = None,
        target_sector: str | None = None,
    ) -> StressReport:
        """Pure path for tests — run scenarios on a pre-built snapshot."""
        target_instrument_id, target_sector = self._resolve_scenario_targets(
            portfolio,
            target_instrument_id=target_instrument_id,
            target_sector=target_sector,
        )
        if scenarios is None:
            raw = self._scenario_engine.run_all(
                portfolio,
                target_instrument_id=target_instrument_id,
                target_sector=target_sector,
            )
            scenarios = tuple(raw[name] for name in ScenarioName)
        return self._build_report(
            profile_id=profile_id,
            portfolio_value_usd=portfolio_value_usd,
            sleeve_risk_budgets=sleeve_risk_budgets,
            scenario_results=scenarios,
            metadata={"mode": "snapshot", "position_count": len(portfolio.positions)},
        )

    def _build_report(
        self,
        *,
        profile_id: str,
        portfolio_value_usd: float,
        sleeve_risk_budgets: dict[str, Decimal],
        scenario_results: tuple[ScenarioResult, ...],
        metadata: dict[str, object],
    ) -> StressReport:
        summaries = tuple(
            summarize_scenario(result, portfolio_value_usd=portfolio_value_usd)
            for result in scenario_results
        )
        worst = min(summaries, key=lambda row: row.estimated_pnl_usd)
        max_loss_fraction = abs(min(0.0, worst.estimated_pnl_impact))
        max_loss_usd = abs(min(0.0, worst.estimated_pnl_usd))
        reviews = build_position_reviews(
            scenario_results,
            portfolio_value_usd=portfolio_value_usd,
            sleeve_risk_budgets=sleeve_risk_budgets,
        )
        return StressReport(
            profile_id=profile_id,
            generated_at=datetime.now(timezone.utc),
            portfolio_value_usd=portfolio_value_usd,
            scenario_results=summaries,
            worst_scenario=worst,
            max_loss_fraction=max_loss_fraction,
            max_loss_usd=max_loss_usd,
            positions_to_review=reviews,
            metadata=metadata,
        )

    @staticmethod
    def _resolve_scenario_targets(
        portfolio: PortfolioSnapshot,
        *,
        target_instrument_id: int | None,
        target_sector: str | None,
    ) -> tuple[int | None, str | None]:
        """Default earnings gap target and sector drought target from portfolio."""
        if target_instrument_id is None and portfolio.positions:
            target_instrument_id = portfolio.positions[0].instrument_id
        if target_sector is None and portfolio.sector_by_instrument:
            first_id = portfolio.positions[0].instrument_id if portfolio.positions else None
            if first_id is not None:
                target_sector = portfolio.sector_by_instrument.get(first_id)
        return target_instrument_id, target_sector
