"""Tests for Prompt 21 ScenarioEngine."""
from __future__ import annotations

import math
import random

import pytest

from app.services.factor.types import FactorName
from app.services.scenario import (
    MonteCarloMethod,
    PortfolioPosition,
    PortfolioSnapshot,
    ScenarioEngine,
    ScenarioName,
    rate_shock,
    run_monte_carlo,
)
from app.services.scenario.portfolio_math import (
    build_covariance_matrix,
    portfolio_return_series,
    stress_correlation_matrix,
)


def _aligned_returns(count: int, *, drift: float, noise: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [drift + noise * rng.gauss(0.0, 1.0) for _ in range(count)]


def _rate_sensitive_portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        positions=(
            PortfolioPosition(instrument_id=1, sleeve_id="core", weight=0.50),
            PortfolioPosition(instrument_id=2, sleeve_id="core", weight=0.30),
            PortfolioPosition(instrument_id=3, sleeve_id="defensive", weight=0.20),
        ),
        factor_exposures={
            1: {FactorName.RATES_SENSITIVITY: 1.2, FactorName.MARKET_BETA: 0.9},
            2: {FactorName.RATES_SENSITIVITY: 0.2, FactorName.MARKET_BETA: 1.0},
            3: {FactorName.RATES_SENSITIVITY: -0.4, FactorName.MARKET_BETA: 0.3},
        },
        returns_by_instrument={
            1: _aligned_returns(40, drift=0.001, noise=0.008, seed=11),
            2: _aligned_returns(40, drift=0.0008, noise=0.007, seed=12),
            3: _aligned_returns(40, drift=0.0002, noise=0.004, seed=13),
        },
        sector_by_instrument={1: "tech", 2: "tech", 3: "utilities"},
    )


class TestPortfolioMath:
    def test_build_covariance_matrix_is_symmetric(self):
        returns = {
            1: _aligned_returns(20, drift=0.001, noise=0.01, seed=1),
            2: _aligned_returns(20, drift=0.0005, noise=0.01, seed=2),
        }
        matrix = build_covariance_matrix(returns, [1, 2])
        assert matrix[0][1] == pytest.approx(matrix[1][0])
        assert matrix[0][0] >= 0.0
        assert matrix[1][1] >= 0.0

    def test_stress_correlation_increases_portfolio_variance(self):
        returns = {
            1: _aligned_returns(30, drift=0.001, noise=0.01, seed=3),
            2: _aligned_returns(30, drift=0.0008, noise=0.01, seed=4),
            3: _aligned_returns(30, drift=-0.0002, noise=0.012, seed=5),
        }
        order = [1, 2, 3]
        baseline = build_covariance_matrix(returns, order)
        stressed = stress_correlation_matrix(baseline, shock_strength=0.5)
        weights = [1 / 3, 1 / 3, 1 / 3]
        from app.services.quant_math import portfolio_variance

        assert portfolio_variance(weights, stressed) > portfolio_variance(weights, baseline)

    def test_portfolio_return_series_weighted(self):
        returns = {1: [0.01, 0.02], 2: [0.03, 0.04]}
        weights = {1: 0.6, 2: 0.4}
        series = portfolio_return_series(returns, weights)
        assert series == pytest.approx([0.6 * 0.01 + 0.4 * 0.03, 0.6 * 0.02 + 0.4 * 0.04])


class TestRateShockScenario:
    def test_rate_shock_hurts_rate_sensitive_instruments(self):
        portfolio = _rate_sensitive_portfolio()
        result = rate_shock(portfolio, shock_strength=100.0)

        impacts = {row.instrument_id: row.pnl_impact for row in result.affected_instruments}
        assert impacts[1] < impacts[2]
        assert impacts[2] < impacts[3]
        assert result.estimated_pnl_impact < 0.0
        assert result.portfolio_variance_delta >= 0.0

    def test_rate_shock_direction_matches_factor_exposure(self):
        portfolio = _rate_sensitive_portfolio()
        result = rate_shock(portfolio, shock_strength=50.0)
        high_rate = next(row for row in result.affected_instruments if row.instrument_id == 1)
        low_rate = next(row for row in result.affected_instruments if row.instrument_id == 3)
        assert high_rate.pnl_impact < low_rate.pnl_impact

    def test_stronger_shock_increases_loss_magnitude(self):
        portfolio = _rate_sensitive_portfolio()
        mild = rate_shock(portfolio, shock_strength=25.0)
        severe = rate_shock(portfolio, shock_strength=100.0)
        assert abs(severe.estimated_pnl_impact) > abs(mild.estimated_pnl_impact)


class TestBuiltInScenarios:
    def test_vix_spike_negative_pnl(self):
        engine = ScenarioEngine()
        result = engine.run(ScenarioName.VIX_SPIKE, _rate_sensitive_portfolio(), shock_strength=0.30)
        assert result.estimated_pnl_impact < 0.0
        assert result.portfolio_variance_delta >= 0.0

    def test_bad_cpi_surprise_negative_for_growth_exposure(self):
        portfolio = PortfolioSnapshot(
            positions=(PortfolioPosition(instrument_id=10, sleeve_id="growth", weight=1.0),),
            factor_exposures={
                10: {
                    FactorName.GROWTH: 1.5,
                    FactorName.RATES_SENSITIVITY: 0.8,
                },
            },
            returns_by_instrument={10: _aligned_returns(30, drift=0.001, noise=0.01, seed=20)},
        )
        engine = ScenarioEngine()
        result = engine.run(ScenarioName.BAD_CPI_SURPRISE, portfolio, shock_strength=0.03)
        assert result.estimated_pnl_impact < 0.0

    def test_sector_liquidity_drought_targets_sector(self):
        portfolio = _rate_sensitive_portfolio()
        engine = ScenarioEngine()
        tech = engine.run(
            ScenarioName.SECTOR_LIQUIDITY_DROUGHT,
            portfolio,
            shock_strength=0.08,
            target_sector="tech",
        )
        utilities = engine.run(
            ScenarioName.SECTOR_LIQUIDITY_DROUGHT,
            portfolio,
            shock_strength=0.08,
            target_sector="utilities",
        )
        tech_loss = sum(
            row.pnl_impact for row in tech.affected_instruments if row.instrument_id in {1, 2}
        )
        util_loss = next(row.pnl_impact for row in utilities.affected_instruments if row.instrument_id == 3)
        assert abs(tech_loss) > abs(util_loss)

    def test_earnings_gap_down_hits_target_instrument(self):
        portfolio = _rate_sensitive_portfolio()
        engine = ScenarioEngine()
        result = engine.run(
            ScenarioName.EARNINGS_GAP_DOWN,
            portfolio,
            shock_strength=0.10,
            target_instrument_id=1,
        )
        target = next(row for row in result.affected_instruments if row.instrument_id == 1)
        others = [row for row in result.affected_instruments if row.instrument_id != 1]
        assert target.pnl_impact < 0.0
        assert all(row.pnl_impact > target.pnl_impact for row in others)

    def test_correlation_breakdown_increases_variance(self):
        portfolio = _rate_sensitive_portfolio()
        engine = ScenarioEngine()
        result = engine.run(ScenarioName.CORRELATION_BREAKDOWN, portfolio, shock_strength=0.40)
        assert result.portfolio_variance_delta > 0.0

    def test_run_all_returns_every_scenario(self):
        engine = ScenarioEngine()
        results = engine.run_all(_rate_sensitive_portfolio(), target_instrument_id=1, target_sector="tech")
        assert set(results.keys()) == set(ScenarioName)


class TestMonteCarlo:
    def test_bootstrap_percentile_ordering(self):
        portfolio = _rate_sensitive_portfolio()
        result = run_monte_carlo(
            portfolio,
            n_simulations=500,
            method=MonteCarloMethod.BOOTSTRAP,
            seed=42,
        )
        bands = result.percentile_bands
        assert bands.p5 <= bands.p25 <= bands.p50 <= bands.p75 <= bands.p95

    def test_parametric_reproducible_with_seed(self):
        portfolio = _rate_sensitive_portfolio()
        first = run_monte_carlo(
            portfolio,
            n_simulations=200,
            method=MonteCarloMethod.PARAMETRIC,
            seed=7,
        )
        second = run_monte_carlo(
            portfolio,
            n_simulations=200,
            method=MonteCarloMethod.PARAMETRIC,
            seed=7,
        )
        assert first.percentile_bands.p50 == pytest.approx(second.percentile_bands.p50)
        assert first.mean_pnl == pytest.approx(second.mean_pnl)

    def test_monte_carlo_via_engine(self):
        engine = ScenarioEngine()
        result = engine.run_monte_carlo(
            _rate_sensitive_portfolio(),
            n_simulations=300,
            method=MonteCarloMethod.BOOTSTRAP,
            seed=99,
        )
        assert result.n_simulations == 300
        assert math.isfinite(result.std_pnl)

    def test_rejects_invalid_simulation_count(self):
        with pytest.raises(ValueError, match="n_simulations"):
            run_monte_carlo(_rate_sensitive_portfolio(), n_simulations=0)

    def test_earnings_gap_requires_target(self):
        engine = ScenarioEngine()
        with pytest.raises(ValueError, match="target_instrument_id"):
            engine.run(ScenarioName.EARNINGS_GAP_DOWN, _rate_sensitive_portfolio())
