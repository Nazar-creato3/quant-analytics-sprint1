"""Unit tests for Terminal Quant/Risk modules — numerical assertions."""
from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.terminal_quant import router as terminal_quant_router
from app.services.quant_math import value_at_risk, VaRMethod
from app.services.terminal_platform.quant.backtest import (
    analyze_backtest,
    run_backtest,
    walk_forward,
)
from app.services.terminal_platform.quant.explainer import RiskExplainer
from app.services.terminal_platform.quant.metrics import (
    beta,
    cagr,
    compute_risk_metrics,
    correlation_pair,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    volatility,
)
from app.services.terminal_platform.quant.models import (
    BacktestConfig,
    CovMatrix,
    ExpectedReturns,
    Portfolio,
    PortfolioPositionWeights,
    PriceSeries,
    QuantRiskLimits,
    ReturnSeries,
    ShockSpec,
    StressScenario,
)
from app.services.terminal_platform.quant.portfolio import (
    efficient_frontier,
    optimize_min_variance,
    optimize_sharpe,
)
from app.services.terminal_platform.quant.risk_bridge import enrich_risk_gate_metadata
from app.services.terminal_platform.quant.risk_manager import (
    evaluate_risk,
    post_trade_check,
    pre_trade_check,
)
from app.services.terminal_platform.quant.stress import shock_analysis, stress_scenario
from app.services.terminal_platform.quant.utils import (
    build_cov_matrix,
    returns_from_prices,
)
from app.services.terminal_platform.quant.var import (
    historical_var,
    monte_carlo_var,
    parametric_var,
)


def _const_growth_prices(n: int = 253, start: float = 100.0, daily: float = 0.001) -> list[float]:
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1.0 + daily))
    return prices


class TestMetrics:
    def test_sharpe_known_series(self):
        # Constant excess return / zero vol edge → 0
        assert sharpe_ratio([0.01, 0.01, 0.01], risk_free_rate=0.0) == 0.0

        returns = [0.01, -0.005, 0.008, 0.002, -0.003, 0.006, 0.004, -0.002]
        rf = 0.0
        ppy = 252
        arr = np.asarray(returns, dtype=float)
        expected = float(arr.mean() / arr.std(ddof=1) * math.sqrt(ppy))
        got = sharpe_ratio(returns, risk_free_rate=rf, periods_per_year=ppy)
        assert got == pytest.approx(expected, rel=1e-9)

    def test_sortino_uses_downside_only(self):
        returns = [0.02, -0.01, 0.03, -0.02, 0.01]
        rf = 0.0
        ppy = 252
        arr = np.asarray(returns, dtype=float)
        period_rf = rf / ppy
        excess = arr - period_rf
        downside = np.minimum(excess, 0.0)
        downside_std = math.sqrt(float(np.mean(downside**2)))
        expected = float(np.mean(excess) / downside_std * math.sqrt(ppy))
        assert sortino_ratio(returns, risk_free_rate=rf, periods_per_year=ppy) == pytest.approx(
            expected, rel=1e-9
        )

    def test_cagr_exact(self):
        # 100 → 110 over 252 periods ≈ 10% CAGR
        prices = [100.0 + i * (10.0 / 252) for i in range(253)]
        # Better: exact geometric
        prices = [100.0 * (1.1 ** (i / 252)) for i in range(253)]
        assert cagr(prices, periods_per_year=252) == pytest.approx(0.10, rel=1e-9)

    def test_volatility_matches_sample_std(self):
        returns = [0.01, -0.02, 0.015, 0.005, -0.01]
        mean = sum(returns) / len(returns)
        expected = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
        assert volatility(returns) == pytest.approx(expected, rel=1e-12)
        assert volatility(returns, annualize=True, periods_per_year=252) == pytest.approx(
            expected * math.sqrt(252), rel=1e-12
        )

    def test_max_drawdown_known(self):
        prices = [100.0, 120.0, 90.0, 95.0]  # peak 120 → 90 = 25%
        assert max_drawdown(prices) == pytest.approx(0.25, rel=1e-12)

    def test_beta_and_correlation(self):
        rng = np.random.default_rng(0)
        market = rng.normal(0.0, 0.01, size=200)
        asset = 1.5 * market + rng.normal(0.0, 0.001, size=200)
        b = beta(asset.tolist(), market.tolist())
        assert b == pytest.approx(1.5, rel=0.05)
        corr = correlation_pair(asset.tolist(), market.tolist())
        assert corr > 0.95

    def test_compute_risk_metrics_bundle(self):
        rng = np.random.default_rng(1)
        rets_raw = rng.normal(0.001, 0.01, size=252).tolist()
        prices = [100.0]
        for r in rets_raw:
            prices.append(prices[-1] * (1.0 + r))
        rets = ReturnSeries(values=rets_raw)
        metrics = compute_risk_metrics(rets, prices=PriceSeries(values=prices))
        assert metrics.n_observations == len(rets.values)
        assert metrics.cagr == pytest.approx(cagr(prices), rel=1e-9)
        assert metrics.max_drawdown >= 0.0
        assert metrics.volatility_annual > 0.0


class TestVaR:
    def test_historical_matches_quant_math(self):
        returns = [0.01, -0.02, 0.015, -0.03, 0.005, -0.01, 0.02, -0.025]
        result = historical_var(returns, 0.95)
        expected = value_at_risk(returns, 0.95, method=VaRMethod.HISTORICAL)
        assert result.var == pytest.approx(expected, rel=1e-12)
        assert result.cvar is not None
        assert result.cvar >= result.var - 1e-12

    def test_parametric_positive_loss(self):
        returns = [-0.01] * 50 + [0.01] * 50
        result = parametric_var(returns, 0.95)
        expected = value_at_risk(returns, 0.95, method=VaRMethod.PARAMETRIC)
        assert result.var == pytest.approx(max(0.0, expected), rel=1e-9)

    def test_monte_carlo_reproducible(self):
        returns = [0.001, -0.002, 0.0015, -0.001, 0.0005] * 40
        a = monte_carlo_var(returns, 0.95, n_simulations=5_000, seed=7)
        b = monte_carlo_var(returns, 0.95, n_simulations=5_000, seed=7)
        assert a.var == pytest.approx(b.var, rel=1e-12)
        assert a.var > 0.0
        assert a.n_simulations == 5_000


class TestPortfolio:
    def test_min_variance_two_asset(self):
        # Asset A vol 10%, B vol 20%, corr 0 → min-var puts more on A
        mu = ExpectedReturns(symbols=["A", "B"], values=[0.08, 0.12])
        cov = CovMatrix(
            symbols=["A", "B"],
            matrix=[[0.01, 0.0], [0.0, 0.04]],
        )
        result = optimize_min_variance(mu, cov, long_only=True)
        assert sum(result.weights) == pytest.approx(1.0, abs=1e-9)
        assert result.weights[0] > result.weights[1]
        # Analytical unconstrained: w_a = σ_b² / (σ_a²+σ_b²) = 0.04/0.05 = 0.8
        assert result.weights[0] == pytest.approx(0.8, rel=1e-6)

    def test_max_sharpe_prefers_higher_reward(self):
        mu = ExpectedReturns(symbols=["A", "B"], values=[0.05, 0.20])
        cov = CovMatrix(
            symbols=["A", "B"],
            matrix=[[0.04, 0.0], [0.0, 0.04]],
        )
        result = optimize_sharpe(mu, cov, risk_free_rate=0.0, long_only=True)
        assert result.weights[1] > result.weights[0]
        assert result.sharpe > 0.0

    def test_efficient_frontier_points(self):
        mu = ExpectedReturns(symbols=["A", "B", "C"], values=[0.05, 0.10, 0.15])
        cov = CovMatrix(
            symbols=["A", "B", "C"],
            matrix=[
                [0.04, 0.01, 0.01],
                [0.01, 0.09, 0.02],
                [0.01, 0.02, 0.16],
            ],
        )
        frontier = efficient_frontier(mu, cov, n_points=10, long_only=True)
        assert len(frontier.points) == 10
        assert frontier.max_sharpe.objective == "max_sharpe"
        assert frontier.min_variance.objective == "min_variance"
        for point in frontier.points:
            assert abs(sum(point.weights) - 1.0) < 1e-8
            assert all(w >= -1e-10 for w in point.weights)


class TestStress:
    def test_equal_weight_uniform_shock(self):
        portfolio = Portfolio(
            value_usd=1_000_000,
            positions=[
                PortfolioPositionWeights(symbol="A", weight=0.5),
                PortfolioPositionWeights(symbol="B", weight=0.5),
            ],
        )
        result = shock_analysis(portfolio, ShockSpec(shocks={"A": -0.10, "B": -0.10}))
        assert result.portfolio_pnl_pct == pytest.approx(-0.10, rel=1e-12)
        assert result.portfolio_pnl_usd == pytest.approx(-100_000.0, rel=1e-9)

    def test_builtin_scenario(self):
        portfolio = Portfolio(
            positions=[PortfolioPositionWeights(symbol="X", weight=1.0)],
            value_usd=10_000,
        )
        result = stress_scenario(portfolio, "equity_crash")
        assert result.portfolio_pnl_pct == pytest.approx(-0.20, rel=1e-12)
        assert result.portfolio_pnl_usd == pytest.approx(-2_000.0, rel=1e-9)

    def test_custom_scenario_partial_shock(self):
        portfolio = Portfolio(
            positions=[
                PortfolioPositionWeights(symbol="A", weight=0.6),
                PortfolioPositionWeights(symbol="B", weight=0.4),
            ],
        )
        scenario = StressScenario(name="custom", asset_shocks={"A": -0.5, "B": 0.0})
        result = stress_scenario(portfolio, scenario)
        assert result.portfolio_pnl_pct == pytest.approx(-0.30, rel=1e-12)


class TestBacktest:
    def test_run_backtest_metrics(self):
        prices = PriceSeries(values=_const_growth_prices(300, daily=0.002))
        result = run_backtest(prices, BacktestConfig(signal_lookback=10))
        assert len(result.equity_curve) == len(prices.values)
        assert result.total_return > 0.0
        assert result.max_drawdown >= 0.0
        assert 0.0 <= result.win_rate <= 1.0
        assert result.sharpe == pytest.approx(result.metrics.sharpe, rel=1e-9)
        assert result.metadata.get("backtest_engine") in {"numpy", "numpy+vectorbt"}

    def test_analyze_backtest_drawdown(self):
        equity = [100.0, 110.0, 88.0, 90.0]
        returns = [0.10, -0.20, 88 / 110 - 1.0]  # unused path — analyzer uses equity for DD
        # Provide consistent returns from equity
        returns = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity))]
        result = analyze_backtest(equity, returns, n_trades=2)
        assert result.max_drawdown == pytest.approx((110 - 88) / 110, rel=1e-12)

    def test_walk_forward_folds(self):
        prices = PriceSeries(values=_const_growth_prices(200, daily=0.001))
        wf = walk_forward(prices, train_window=40, test_window=20, params=BacktestConfig(signal_lookback=5))
        assert len(wf.folds) >= 1
        assert wf.aggregate.n_trades >= 0
        assert isinstance(wf.mean_test_sharpe, float)


class TestRiskManagerAndExplainer:
    def test_pre_trade_blocks_oversized_weight(self):
        portfolio = Portfolio(positions=[PortfolioPositionWeights(symbol="A", weight=1.0)])
        returns = ReturnSeries(values=[0.01, -0.01, 0.005, -0.002] * 20)
        decision = pre_trade_check(
            order_symbol="B",
            proposed_weight=0.50,
            portfolio=portfolio,
            historical_returns=returns,
            limits=QuantRiskLimits(max_position_weight=0.25, enforce=False),
        )
        assert decision.approved is False
        assert "weight" in decision.reason
        assert decision.metadata["enforce"] is False
        assert decision.metadata["soft_pass"] is True

    def test_evaluate_risk_passes_small_weight(self):
        portfolio = Portfolio(positions=[PortfolioPositionWeights(symbol="A", weight=1.0)])
        returns = ReturnSeries(values=[0.001, -0.001, 0.0005] * 30)
        decision = evaluate_risk(
            order_symbol="A",
            proposed_weight=0.10,
            portfolio=portfolio,
            historical_returns=returns,
            limits=QuantRiskLimits(max_position_weight=0.25, max_portfolio_var=0.50),
        )
        assert decision.approved is True
        assert decision.var is not None

    def test_post_trade_flags_drawdown(self):
        prices = PriceSeries(values=[100.0, 120.0, 60.0, 65.0])
        returns = returns_from_prices(prices.values)
        portfolio = Portfolio(positions=[PortfolioPositionWeights(symbol="A", weight=1.0)])
        decision = post_trade_check(
            portfolio=portfolio,
            historical_returns=returns,
            prices=prices,
            limits=QuantRiskLimits(max_drawdown=0.20, max_portfolio_var=1.0, max_daily_loss=1.0),
        )
        assert decision.approved is False
        assert decision.drawdown == pytest.approx(0.5, rel=1e-9)

    def test_explainer_contains_numbers(self):
        prices = PriceSeries(values=_const_growth_prices(100))
        rets = returns_from_prices(prices.values)
        metrics = compute_risk_metrics(rets, prices=prices)
        text = RiskExplainer().explain_metrics(metrics)
        assert "Sharpe" in text
        assert f"{metrics.sharpe:.2f}" in text
        var = historical_var(rets, 0.95)
        var_text = RiskExplainer().explain_var(var)
        assert "95%" in var_text or "0.95" in var_text or "95" in var_text

    def test_risk_bridge_enrichment(self):
        meta = enrich_risk_gate_metadata(
            {"ok": True},
            symbol="AAPL",
            proposed_weight=0.05,
            historical_returns=[0.01, -0.01, 0.0] * 10,
        )
        assert "terminal_quant" in meta
        assert meta["terminal_quant"].get("skipped") is not True


class TestAPI:
    def _client(self):
        from app.core.deps import get_current_user_email

        app = FastAPI()
        app.include_router(terminal_quant_router, prefix="/api/v1")
        app.dependency_overrides[get_current_user_email] = lambda: "user@example.com"
        return TestClient(app)

    def test_metrics_requires_auth(self):
        app = FastAPI()
        app.include_router(terminal_quant_router, prefix="/api/v1")
        client = TestClient(app)
        response = client.post(
            "/api/v1/terminal/quant/metrics",
            json={"returns": {"values": [0.01, -0.01], "periods_per_year": 252}},
        )
        assert response.status_code in (401, 403)

    def test_metrics_endpoint(self):
        client = self._client()
        prices = _const_growth_prices(60)
        rets = returns_from_prices(prices).values
        response = client.post(
            "/api/v1/terminal/quant/metrics",
            json={
                "returns": {"values": rets, "periods_per_year": 252},
                "prices": {"values": prices, "periods_per_year": 252},
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "sharpe" in body
        assert body["n_observations"] == len(rets)

    def test_var_and_frontier_endpoints(self):
        client = self._client()
        var_resp = client.post(
            "/api/v1/terminal/quant/var",
            json={
                "returns": {"values": [0.01, -0.02, 0.015, -0.01] * 10},
                "confidence": 0.95,
                "method": "historical",
            },
        )
        assert var_resp.status_code == 200
        assert var_resp.json()["var"] >= 0.0

        frontier = client.post(
            "/api/v1/terminal/quant/portfolio/frontier",
            json={
                "expected_returns": {"symbols": ["A", "B"], "values": [0.08, 0.12]},
                "cov_matrix": {
                    "symbols": ["A", "B"],
                    "matrix": [[0.01, 0.0], [0.0, 0.04]],
                },
                "n_frontier_points": 5,
            },
        )
        assert frontier.status_code == 200
        assert len(frontier.json()["points"]) == 5

    def test_build_cov_matrix_helper(self):
        cov = build_cov_matrix({"A": [0.01, 0.02, -0.01], "B": [0.0, 0.01, -0.02]})
        assert cov.symbols == ["A", "B"]
        assert len(cov.matrix) == 2
