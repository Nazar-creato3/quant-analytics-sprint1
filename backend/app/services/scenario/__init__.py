"""Portfolio stress scenario engine (Prompt 21)."""
from __future__ import annotations

from app.services.scenario.engine import ScenarioEngine, ScenarioEngineConfig
from app.services.scenario.monte_carlo import run_monte_carlo
from app.services.scenario.scenarios import (
    SCENARIO_RUNNERS,
    bad_cpi_surprise,
    correlation_breakdown,
    earnings_gap_down,
    rate_shock,
    sector_liquidity_drought,
    vix_spike,
)
from app.services.scenario.types import (
    AffectedInstrument,
    AffectedSleeve,
    MonteCarloMethod,
    MonteCarloResult,
    PercentileBands,
    PortfolioPosition,
    PortfolioSnapshot,
    ScenarioName,
    ScenarioResult,
)

__all__ = [
    "AffectedInstrument",
    "AffectedSleeve",
    "MonteCarloMethod",
    "MonteCarloResult",
    "PercentileBands",
    "PortfolioPosition",
    "PortfolioSnapshot",
    "SCENARIO_RUNNERS",
    "ScenarioEngine",
    "ScenarioEngineConfig",
    "ScenarioName",
    "ScenarioResult",
    "bad_cpi_surprise",
    "correlation_breakdown",
    "earnings_gap_down",
    "rate_shock",
    "run_monte_carlo",
    "sector_liquidity_drought",
    "vix_spike",
]
