"""ScenarioEngine — portfolio stress scenarios and Monte Carlo (Prompt 21)."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.scenario.monte_carlo import run_monte_carlo
from app.services.scenario.scenarios import SCENARIO_RUNNERS
from app.services.scenario.types import (
    MonteCarloMethod,
    MonteCarloResult,
    PortfolioSnapshot,
    ScenarioName,
    ScenarioResult,
)


@dataclass(frozen=True, slots=True)
class ScenarioEngineConfig:
    """Default shock strengths for built-in scenarios."""

    default_rate_shock_bps: float = 50.0
    default_vix_spike_pct: float = 0.25
    default_cpi_surprise: float = 0.02
    default_liquidity_drought: float = 0.05
    default_earnings_gap: float = 0.08
    default_correlation_shock: float = 0.30


class ScenarioEngine:
    """Run built-in stress scenarios and Monte Carlo on a portfolio snapshot."""

    def __init__(self, *, config: ScenarioEngineConfig | None = None) -> None:
        self._config = config or ScenarioEngineConfig()

    def run(
        self,
        scenario: ScenarioName,
        portfolio: PortfolioSnapshot,
        shock_strength: float | None = None,
        *,
        target_instrument_id: int | None = None,
        target_sector: str | None = None,
    ) -> ScenarioResult:
        """Execute a built-in scenario against the portfolio."""
        runner = SCENARIO_RUNNERS[scenario]
        strength = shock_strength if shock_strength is not None else self._default_strength(scenario)

        if scenario == ScenarioName.EARNINGS_GAP_DOWN:
            if target_instrument_id is None:
                raise ValueError("target_instrument_id is required for earnings_gap_down.")
            return runner(portfolio, strength, target_instrument_id=target_instrument_id)

        if scenario == ScenarioName.SECTOR_LIQUIDITY_DROUGHT:
            return runner(portfolio, strength, target_sector=target_sector)

        return runner(portfolio, strength)

    def run_all(
        self,
        portfolio: PortfolioSnapshot,
        *,
        target_instrument_id: int | None = None,
        target_sector: str | None = None,
    ) -> dict[ScenarioName, ScenarioResult]:
        """Run every built-in scenario with default shock strengths."""
        results: dict[ScenarioName, ScenarioResult] = {}
        for scenario in ScenarioName:
            results[scenario] = self.run(
                scenario,
                portfolio,
                target_instrument_id=target_instrument_id,
                target_sector=target_sector,
            )
        return results

    def run_monte_carlo(
        self,
        portfolio: PortfolioSnapshot,
        *,
        n_simulations: int = 1000,
        method: MonteCarloMethod = MonteCarloMethod.BOOTSTRAP,
        seed: int | None = None,
    ) -> MonteCarloResult:
        """Monte Carlo P&L distribution with bootstrap or parametric sampling."""
        return run_monte_carlo(
            portfolio,
            n_simulations=n_simulations,
            method=method,
            seed=seed,
        )

    def _default_strength(self, scenario: ScenarioName) -> float:
        defaults = {
            ScenarioName.RATE_SHOCK: self._config.default_rate_shock_bps,
            ScenarioName.VIX_SPIKE: self._config.default_vix_spike_pct,
            ScenarioName.BAD_CPI_SURPRISE: self._config.default_cpi_surprise,
            ScenarioName.SECTOR_LIQUIDITY_DROUGHT: self._config.default_liquidity_drought,
            ScenarioName.EARNINGS_GAP_DOWN: self._config.default_earnings_gap,
            ScenarioName.CORRELATION_BREAKDOWN: self._config.default_correlation_shock,
        }
        return defaults[scenario]
