"""Scenario stress-test types for Prompt 21 Scenario Engine."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.services.factor.types import FactorName


class ScenarioName(StrEnum):
    """Built-in stress scenarios."""

    RATE_SHOCK = "rate_shock"
    VIX_SPIKE = "vix_spike"
    BAD_CPI_SURPRISE = "bad_cpi_surprise"
    SECTOR_LIQUIDITY_DROUGHT = "sector_liquidity_drought"
    EARNINGS_GAP_DOWN = "earnings_gap_down"
    CORRELATION_BREAKDOWN = "correlation_breakdown"


class MonteCarloMethod(StrEnum):
    """Supported Monte Carlo sampling methods."""

    BOOTSTRAP = "bootstrap"
    PARAMETRIC = "parametric"


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    """Single portfolio position with sleeve attribution."""

    instrument_id: int
    sleeve_id: str
    weight: float


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """Portfolio input for scenario and Monte Carlo analysis."""

    positions: tuple[PortfolioPosition, ...]
    factor_exposures: dict[int, dict[FactorName, float]]
    returns_by_instrument: dict[int, list[float]]
    sector_by_instrument: dict[int, str] | None = None


@dataclass(frozen=True, slots=True)
class AffectedInstrument:
    """Instrument-level stress impact."""

    instrument_id: int
    sleeve_id: str
    weight: float
    pnl_impact: float
    contribution_pct: float


@dataclass(frozen=True, slots=True)
class AffectedSleeve:
    """Sleeve-level stress impact."""

    sleeve_id: str
    pnl_impact: float
    contribution_pct: float


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """Output of a single stress scenario."""

    scenario_name: ScenarioName
    shock_strength: float
    baseline_portfolio_variance: float
    stressed_portfolio_variance: float
    portfolio_variance_delta: float
    estimated_pnl_impact: float
    affected_instruments: tuple[AffectedInstrument, ...]
    affected_sleeves: tuple[AffectedSleeve, ...]


@dataclass(frozen=True, slots=True)
class PercentileBands:
    """Monte Carlo P&L percentile bands (fraction of portfolio)."""

    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    """Monte Carlo distribution of portfolio P&L outcomes."""

    method: MonteCarloMethod
    n_simulations: int
    percentile_bands: PercentileBands
    mean_pnl: float
    std_pnl: float
