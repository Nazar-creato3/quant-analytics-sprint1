"""Built-in stress scenario functions for ScenarioEngine."""
from __future__ import annotations

from typing import Callable

from app.services.factor.types import FactorName
from app.services.scenario.portfolio_math import (
    aggregate_sleeve_impacts,
    build_covariance_matrix,
    instrument_order,
    portfolio_variance_for,
    scale_diagonal_volatility,
    stress_correlation_matrix,
    weight_vector,
    weights_by_instrument,
)
from app.services.scenario.types import (
    AffectedInstrument,
    AffectedSleeve,
    PortfolioSnapshot,
    ScenarioName,
    ScenarioResult,
)


def _beta(exposures: dict[FactorName, float], factor: FactorName) -> float:
    return exposures.get(factor, 0.0)


def _build_result(
    *,
    scenario_name: ScenarioName,
    shock_strength: float,
    portfolio: PortfolioSnapshot,
    instrument_pnl: dict[int, float],
    stressed_covariance: list[list[float]] | None = None,
) -> ScenarioResult:
    order = instrument_order(portfolio)
    baseline_cov = build_covariance_matrix(portfolio.returns_by_instrument, order)
    baseline_variance = portfolio_variance_for(portfolio, covariance_matrix=baseline_cov)
    stressed_variance = (
        portfolio_variance_for(
            portfolio,
            covariance_matrix=stressed_covariance,
        )
        if stressed_covariance is not None
        else baseline_variance
    )

    position_lookup = {
        position.instrument_id: position
        for position in portfolio.positions
    }
    total_abs = sum(abs(value) for value in instrument_pnl.values())
    affected_instruments: list[AffectedInstrument] = []
    sleeve_rows: list[tuple[str, float]] = []
    for instrument_id in sorted(instrument_pnl, key=lambda key: instrument_pnl[key]):
        impact = instrument_pnl[instrument_id]
        position = position_lookup[instrument_id]
        contribution = (abs(impact) / total_abs * 100.0) if total_abs > 0.0 else 0.0
        affected_instruments.append(
            AffectedInstrument(
                instrument_id=instrument_id,
                sleeve_id=position.sleeve_id,
                weight=position.weight,
                pnl_impact=impact,
                contribution_pct=contribution,
            )
        )
        sleeve_rows.append((position.sleeve_id, impact))

    affected_sleeves = tuple(
        AffectedSleeve(
            sleeve_id=sleeve_id,
            pnl_impact=impact,
            contribution_pct=contribution,
        )
        for sleeve_id, impact, contribution in aggregate_sleeve_impacts(sleeve_rows)
    )
    estimated_pnl = sum(instrument_pnl.values())
    return ScenarioResult(
        scenario_name=scenario_name,
        shock_strength=shock_strength,
        baseline_portfolio_variance=baseline_variance,
        stressed_portfolio_variance=stressed_variance,
        portfolio_variance_delta=stressed_variance - baseline_variance,
        estimated_pnl_impact=estimated_pnl,
        affected_instruments=tuple(affected_instruments),
        affected_sleeves=affected_sleeves,
    )


def _factor_shock_pnl(
    portfolio: PortfolioSnapshot,
    *,
    factor_weights: dict[FactorName, float],
    shock_magnitude: float,
) -> dict[int, float]:
    """Map factor shock to instrument P&L using exposures and position weights."""
    pnl: dict[int, float] = {}
    for position in portfolio.positions:
        exposures = portfolio.factor_exposures.get(position.instrument_id, {})
        shock_return = sum(
            _beta(exposures, factor) * weight * shock_magnitude
            for factor, weight in factor_weights.items()
        )
        pnl[position.instrument_id] = pnl.get(position.instrument_id, 0.0) + position.weight * shock_return
    return pnl


def _vol_multipliers_from_exposures(
    portfolio: PortfolioSnapshot,
    order: list[int],
    *,
    factor: FactorName,
    shock_strength: float,
) -> list[float]:
    multipliers: list[float] = []
    for instrument_id in order:
        exposures = portfolio.factor_exposures.get(instrument_id, {})
        sensitivity = abs(_beta(exposures, factor))
        multipliers.append(1.0 + sensitivity * shock_strength)
    return multipliers


def rate_shock(portfolio: PortfolioSnapshot, shock_strength: float) -> ScenarioResult:
    """Rates +N basis points — hurts rate-sensitive instruments via beta."""
    rate_move = shock_strength / 10_000.0
    instrument_pnl = _factor_shock_pnl(
        portfolio,
        factor_weights={FactorName.RATES_SENSITIVITY: -rate_move},
        shock_magnitude=1.0,
    )
    order = instrument_order(portfolio)
    baseline_cov = build_covariance_matrix(portfolio.returns_by_instrument, order)
    vol_multipliers = _vol_multipliers_from_exposures(
        portfolio,
        order,
        factor=FactorName.RATES_SENSITIVITY,
        shock_strength=abs(rate_move) * 100.0,
    )
    stressed_cov = scale_diagonal_volatility(baseline_cov, vol_multipliers)
    return _build_result(
        scenario_name=ScenarioName.RATE_SHOCK,
        shock_strength=shock_strength,
        portfolio=portfolio,
        instrument_pnl=instrument_pnl,
        stressed_covariance=stressed_cov,
    )


def vix_spike(portfolio: PortfolioSnapshot, shock_strength: float) -> ScenarioResult:
    """VIX +X% — equity drawdown scaled by vol and macro shock betas."""
    vix_fraction = shock_strength
    instrument_pnl = _factor_shock_pnl(
        portfolio,
        factor_weights={
            FactorName.VOLATILITY_FACTOR: -0.6 * vix_fraction,
            FactorName.MACRO_SHOCK_SENSITIVITY: -0.4 * vix_fraction,
            FactorName.MARKET_BETA: -0.3 * vix_fraction,
        },
        shock_magnitude=1.0,
    )
    order = instrument_order(portfolio)
    baseline_cov = build_covariance_matrix(portfolio.returns_by_instrument, order)
    vol_multipliers = [
        1.0
        + abs(_beta(portfolio.factor_exposures.get(instrument_id, {}), FactorName.VOLATILITY_FACTOR))
        * vix_fraction
        for instrument_id in order
    ]
    stressed_cov = scale_diagonal_volatility(baseline_cov, vol_multipliers)
    return _build_result(
        scenario_name=ScenarioName.VIX_SPIKE,
        shock_strength=shock_strength,
        portfolio=portfolio,
        instrument_pnl=instrument_pnl,
        stressed_covariance=stressed_cov,
    )


def bad_cpi_surprise(portfolio: PortfolioSnapshot, shock_strength: float) -> ScenarioResult:
    """Hot CPI surprise — rates up, growth down, commodity pressure."""
    surprise = shock_strength
    instrument_pnl = _factor_shock_pnl(
        portfolio,
        factor_weights={
            FactorName.RATES_SENSITIVITY: -0.5 * surprise,
            FactorName.GROWTH: -0.35 * surprise,
            FactorName.COMMODITY_SENSITIVITY: 0.15 * surprise,
            FactorName.MACRO_SHOCK_SENSITIVITY: -0.25 * surprise,
        },
        shock_magnitude=1.0,
    )
    order = instrument_order(portfolio)
    baseline_cov = build_covariance_matrix(portfolio.returns_by_instrument, order)
    vol_multipliers = _vol_multipliers_from_exposures(
        portfolio,
        order,
        factor=FactorName.MACRO_SHOCK_SENSITIVITY,
        shock_strength=surprise,
    )
    stressed_cov = scale_diagonal_volatility(baseline_cov, vol_multipliers)
    return _build_result(
        scenario_name=ScenarioName.BAD_CPI_SURPRISE,
        shock_strength=shock_strength,
        portfolio=portfolio,
        instrument_pnl=instrument_pnl,
        stressed_covariance=stressed_cov,
    )


def sector_liquidity_drought(
    portfolio: PortfolioSnapshot,
    shock_strength: float,
    *,
    target_sector: str | None = None,
) -> ScenarioResult:
    """Sector liquidity drought — widened spreads and slippage on affected names."""
    sector_map = portfolio.sector_by_instrument or {}
    drought_penalty = shock_strength
    instrument_pnl: dict[int, float] = {}
    order = instrument_order(portfolio)
    vol_multipliers = [1.0] * len(order)

    for index, instrument_id in enumerate(order):
        sector = sector_map.get(instrument_id)
        in_sector = target_sector is None or sector == target_sector
        exposures = portfolio.factor_exposures.get(instrument_id, {})
        vol_beta = abs(_beta(exposures, FactorName.VOLATILITY_FACTOR))
        sector_beta = abs(_beta(exposures, FactorName.SECTOR_FACTOR))
        if in_sector:
            impact = -drought_penalty * (0.6 + 0.4 * vol_beta + 0.2 * sector_beta)
            vol_multipliers[index] = 1.0 + drought_penalty * (1.0 + vol_beta)
        else:
            impact = -drought_penalty * 0.1 * vol_beta
            vol_multipliers[index] = 1.0 + drought_penalty * 0.15 * vol_beta
        for position in portfolio.positions:
            if position.instrument_id == instrument_id:
                instrument_pnl[instrument_id] = instrument_pnl.get(instrument_id, 0.0) + position.weight * impact

    baseline_cov = build_covariance_matrix(portfolio.returns_by_instrument, order)
    stressed_cov = scale_diagonal_volatility(baseline_cov, vol_multipliers)
    return _build_result(
        scenario_name=ScenarioName.SECTOR_LIQUIDITY_DROUGHT,
        shock_strength=shock_strength,
        portfolio=portfolio,
        instrument_pnl=instrument_pnl,
        stressed_covariance=stressed_cov,
    )


def earnings_gap_down(
    portfolio: PortfolioSnapshot,
    shock_strength: float,
    *,
    target_instrument_id: int,
) -> ScenarioResult:
    """Gap-down on a single instrument — shock_strength is fractional drop (e.g. 0.08)."""
    gap = -abs(shock_strength)
    instrument_pnl: dict[int, float] = {}
    for position in portfolio.positions:
        if position.instrument_id == target_instrument_id:
            instrument_pnl[position.instrument_id] = (
                instrument_pnl.get(position.instrument_id, 0.0) + position.weight * gap
            )
        else:
            exposures = portfolio.factor_exposures.get(position.instrument_id, {})
            spillover = gap * 0.15 * _beta(exposures, FactorName.SECTOR_FACTOR)
            instrument_pnl[position.instrument_id] = (
                instrument_pnl.get(position.instrument_id, 0.0) + position.weight * spillover
            )

    order = instrument_order(portfolio)
    baseline_cov = build_covariance_matrix(portfolio.returns_by_instrument, order)
    vol_multipliers = [1.0] * len(order)
    if target_instrument_id in order:
        target_index = order.index(target_instrument_id)
        vol_multipliers[target_index] = 1.0 + abs(gap) * 2.0
    stressed_cov = scale_diagonal_volatility(baseline_cov, vol_multipliers)
    return _build_result(
        scenario_name=ScenarioName.EARNINGS_GAP_DOWN,
        shock_strength=shock_strength,
        portfolio=portfolio,
        instrument_pnl=instrument_pnl,
        stressed_covariance=stressed_cov,
    )


def correlation_breakdown(portfolio: PortfolioSnapshot, shock_strength: float) -> ScenarioResult:
    """Rising cross-asset correlations — diversification breakdown."""
    order = instrument_order(portfolio)
    baseline_cov = build_covariance_matrix(portfolio.returns_by_instrument, order)
    stressed_cov = stress_correlation_matrix(baseline_cov, shock_strength)
    weights = weight_vector(portfolio, order)
    contagion = shock_strength * 0.05
    instrument_pnl = {
        instrument_id: -contagion * weight
        for instrument_id, weight in zip(order, weights)
    }
    return _build_result(
        scenario_name=ScenarioName.CORRELATION_BREAKDOWN,
        shock_strength=shock_strength,
        portfolio=portfolio,
        instrument_pnl=instrument_pnl,
        stressed_covariance=stressed_cov,
    )


SCENARIO_RUNNERS: dict[ScenarioName, Callable[..., ScenarioResult]] = {
    ScenarioName.RATE_SHOCK: rate_shock,
    ScenarioName.VIX_SPIKE: vix_spike,
    ScenarioName.BAD_CPI_SURPRISE: bad_cpi_surprise,
    ScenarioName.SECTOR_LIQUIDITY_DROUGHT: sector_liquidity_drought,
    ScenarioName.EARNINGS_GAP_DOWN: earnings_gap_down,
    ScenarioName.CORRELATION_BREAKDOWN: correlation_breakdown,
}
