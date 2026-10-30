"""Tests for Prompt 27 StressHarness."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.factor.types import FactorName
from app.services.scenario import PortfolioPosition, PortfolioSnapshot, ScenarioName
from app.services.stress_harness import CustomScenarioRequest, StressHarness
from app.services.stress_harness.types import build_position_reviews, summarize_scenario
from app.tests.test_scenario_engine import _aligned_returns, _rate_sensitive_portfolio


def _portfolio() -> PortfolioSnapshot:
    return _rate_sensitive_portfolio()


class TestStressHarnessReport:
    def test_run_all_scenarios_returns_every_builtin(self):
        harness = StressHarness()
        report = harness.run_on_snapshot(
            profile_id="test-profile",
            portfolio=_portfolio(),
            portfolio_value_usd=100_000.0,
            sleeve_risk_budgets={
                "core": Decimal("5000"),
                "defensive": Decimal("3000"),
            },
        )
        assert len(report.scenario_results) == len(ScenarioName)
        assert {row.scenario_name for row in report.scenario_results} == set(ScenarioName)

    def test_worst_scenario_is_max_loss(self):
        harness = StressHarness()
        report = harness.run_on_snapshot(
            profile_id="test-profile",
            portfolio=_portfolio(),
            portfolio_value_usd=100_000.0,
            sleeve_risk_budgets={"core": Decimal("5000"), "defensive": Decimal("3000")},
        )
        losses = [row.estimated_pnl_usd for row in report.scenario_results]
        assert report.worst_scenario.estimated_pnl_usd == min(losses)
        assert report.max_loss_usd == abs(min(losses))

    def test_rate_shock_negative_pnl(self):
        harness = StressHarness()
        report = harness.run_on_snapshot(
            profile_id="test-profile",
            portfolio=_portfolio(),
            portfolio_value_usd=100_000.0,
            sleeve_risk_budgets={"core": Decimal("5000"), "defensive": Decimal("3000")},
        )
        rate = next(row for row in report.scenario_results if row.scenario_name == ScenarioName.RATE_SHOCK)
        assert rate.estimated_pnl_impact < 0.0
        assert rate.estimated_pnl_usd < 0.0

    def test_vix_spike_negative_pnl(self):
        harness = StressHarness()
        report = harness.run_on_snapshot(
            profile_id="test-profile",
            portfolio=_portfolio(),
            portfolio_value_usd=100_000.0,
            sleeve_risk_budgets={"core": Decimal("5000"), "defensive": Decimal("3000")},
        )
        vix = next(row for row in report.scenario_results if row.scenario_name == ScenarioName.VIX_SPIKE)
        assert vix.estimated_pnl_impact < 0.0

    def test_correlation_breakdown_increases_variance(self):
        harness = StressHarness()
        report = harness.run_on_snapshot(
            profile_id="test-profile",
            portfolio=_portfolio(),
            portfolio_value_usd=100_000.0,
            sleeve_risk_budgets={"core": Decimal("5000"), "defensive": Decimal("3000")},
        )
        corr = next(
            row for row in report.scenario_results if row.scenario_name == ScenarioName.CORRELATION_BREAKDOWN
        )
        assert corr.portfolio_variance_delta > 0.0

    def test_custom_scenario_runs_single_case(self):
        harness = StressHarness()
        context_portfolio = _portfolio()
        report = harness.run_custom_scenario(
            type(
                "Ctx",
                (),
                {
                    "profile_id": "test-profile",
                    "portfolio": context_portfolio,
                    "portfolio_value_usd": 100_000.0,
                    "sleeve_risk_budgets": {"core": Decimal("5000"), "defensive": Decimal("3000")},
                },
            )(),
            CustomScenarioRequest(
                scenario=ScenarioName.RATE_SHOCK,
                shock_strength=75.0,
            ),
        )
        assert len(report.scenario_results) == 1
        assert report.scenario_results[0].scenario_name == ScenarioName.RATE_SHOCK
        assert report.scenario_results[0].shock_strength == pytest.approx(75.0)

    def test_stronger_custom_shock_increases_loss(self):
        harness = StressHarness()
        ctx = type(
            "Ctx",
            (),
            {
                "profile_id": "test-profile",
                "portfolio": _portfolio(),
                "portfolio_value_usd": 100_000.0,
                "sleeve_risk_budgets": {"core": Decimal("5000"), "defensive": Decimal("3000")},
            },
        )()
        mild = harness.run_custom_scenario(
            ctx,
            CustomScenarioRequest(scenario=ScenarioName.RATE_SHOCK, shock_strength=25.0),
        )
        severe = harness.run_custom_scenario(
            ctx,
            CustomScenarioRequest(scenario=ScenarioName.RATE_SHOCK, shock_strength=100.0),
        )
        assert abs(severe.max_loss_usd) > abs(mild.max_loss_usd)

    def test_positions_to_review_when_stress_exceeds_budget(self):
        harness = StressHarness()
        portfolio = PortfolioSnapshot(
            positions=(PortfolioPosition(instrument_id=1, sleeve_id="core", weight=1.0),),
            factor_exposures={
                1: {FactorName.RATES_SENSITIVITY: 2.0, FactorName.MARKET_BETA: 1.0},
            },
            returns_by_instrument={
                1: _aligned_returns(30, drift=0.001, noise=0.01, seed=99),
            },
        )
        report = harness.run_on_snapshot(
            profile_id="test-profile",
            portfolio=portfolio,
            portfolio_value_usd=100_000.0,
            sleeve_risk_budgets={"core": Decimal("50")},
        )
        assert report.positions_to_review
        assert all(row.exceeds_budget for row in report.positions_to_review)
        assert report.positions_to_review[0].instrument_id == 1

    def test_report_to_dict_contains_scenario_names(self):
        harness = StressHarness()
        report = harness.run_on_snapshot(
            profile_id="test-profile",
            portfolio=_portfolio(),
            portfolio_value_usd=100_000.0,
            sleeve_risk_budgets={"core": Decimal("5000"), "defensive": Decimal("3000")},
        )
        payload = report.to_dict()
        assert payload["profile_id"] == "test-profile"
        assert len(payload["scenario_results"]) == len(ScenarioName)
        assert payload["worst_scenario"]["scenario_name"] in {name.value for name in ScenarioName}


class TestStressHarnessHelpers:
    def test_summarize_scenario_converts_usd(self):
        harness = StressHarness()
        raw = harness._scenario_engine.run(ScenarioName.RATE_SHOCK, _portfolio(), shock_strength=50.0)
        summary = summarize_scenario(raw, portfolio_value_usd=200_000.0)
        assert summary.estimated_pnl_usd == pytest.approx(raw.estimated_pnl_impact * 200_000.0)

    def test_build_position_reviews_skips_within_budget(self):
        harness = StressHarness()
        raw = harness._scenario_engine.run_all(_portfolio(), target_instrument_id=1, target_sector="tech")
        reviews = build_position_reviews(
            tuple(raw.values()),
            portfolio_value_usd=100_000.0,
            sleeve_risk_budgets={"core": Decimal("1000000"), "defensive": Decimal("1000000")},
        )
        assert reviews == ()
