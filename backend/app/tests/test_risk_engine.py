"""Tests for Prompt 23 RiskEngine and RiskGate integration."""
from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.domain.enums import AssetCategory
from app.services.control_fabric import (
    OpenPositionExposure,
    RiskEngine,
    RiskEngineInput,
    RiskGate,
    RiskGateOutcome,
    RiskBudgetContext,
)
from app.services.control_fabric.risk_engine import (
    compute_concentration_pct,
    compute_drawdown_risk,
    compute_factor_concentration,
    compute_gap_risk_probability,
    compute_correlation_cluster_weight,
)
from app.services.factor.types import FactorName
from app.services.market_graph.builder import build_correlation_edges
from app.services.scenario.types import PortfolioPosition
from app.tests.test_approval_policy_engine import _context, _intent, _profile


def _returns(count: int, *, drift: float = 0.0, vol: float = 0.02, seed: int = 1) -> list[float]:
    rng = random.Random(seed)
    return [drift + vol * rng.gauss(0.0, 1.0) for _ in range(count)]


def _budget(**overrides: object) -> RiskBudgetContext:
    defaults = {
        "diversification_policy": {},
        "max_drawdown_pct": 15.0,
        "sleeve_risk_budget": Decimal("10000"),
        "profile_max_daily_loss": Decimal("5000"),
    }
    defaults.update(overrides)
    return RiskBudgetContext(**defaults)


def _sleeve(**overrides: object):
    from datetime import datetime, timezone

    from app.domain.sleeve import SleeveRead

    _NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
    defaults = {
        "id": "sleeve-1",
        "profile_id": "user-1",
        "name": "Core",
        "category": AssetCategory.EQUITIES,
        "capital_allocation_pct": Decimal("60"),
        "risk_budget": Decimal("10000"),
        "status": "active",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return SleeveRead(**defaults)


class TestRiskMetricComputations:
    def test_drawdown_risk_at_peak_is_zero(self):
        prices = [100.0, 105.0, 110.0, 115.0]
        assert compute_drawdown_risk(prices) == 0.0

    def test_drawdown_risk_detects_decline_from_peak(self):
        prices = [100.0, 110.0, 99.0, 88.0]
        drawdown = compute_drawdown_risk(prices)
        assert drawdown == pytest.approx(0.2, rel=1e-3)

    def test_gap_risk_high_on_frequent_large_overnight_moves(self):
        calm = [0.001, -0.001, 0.0005, -0.0005, 0.001] * 10
        assert compute_gap_risk_probability(calm) < 0.1

        volatile = [0.001, -0.001, 0.08, -0.07, 0.06, -0.05] * 5
        assert compute_gap_risk_probability(volatile) > 0.3

    def test_factor_concentration_detects_dominant_factor(self):
        positions = (
            PortfolioPosition(instrument_id=1, sleeve_id="core", weight=0.6),
            PortfolioPosition(instrument_id=2, sleeve_id="core", weight=0.4),
        )
        exposures = {
            1: {FactorName.RATES_SENSITIVITY: 1.5, FactorName.MARKET_BETA: 0.2},
            2: {FactorName.RATES_SENSITIVITY: 1.2, FactorName.MARKET_BETA: 0.1},
        }
        concentration, totals = compute_factor_concentration(positions, exposures)
        assert concentration == pytest.approx(0.6 * 1.5 + 0.4 * 1.2, rel=1e-3)
        assert totals[FactorName.RATES_SENSITIVITY.value] == pytest.approx(concentration)

    def test_concentration_pct_by_instrument(self):
        positions = (
            PortfolioPosition(instrument_id=1, sleeve_id="a", weight=0.70),
            PortfolioPosition(instrument_id=2, sleeve_id="a", weight=0.30),
        )
        assert compute_concentration_pct(positions, sector_by_instrument={}, group_key="instrument") == pytest.approx(70.0)


class TestRiskEngineAssessment:
    def test_var_at_limit_flags_breach(self):
        engine = RiskEngine()
        volatile_returns = _returns(60, vol=0.08, seed=42)
        inputs = RiskEngineInput(
            instrument_id=101,
            returns_by_instrument={101: volatile_returns},
            positions=(PortfolioPosition(instrument_id=101, sleeve_id="core", weight=1.0),),
        )
        budget = _budget(
            diversification_policy={"max_var_95": 0.01, "max_var_99": 0.02},
        )
        assessment = engine.assess(inputs, budget)
        var_metrics = [m for m in assessment.metrics if m.name == "var_95"]
        assert var_metrics
        assert var_metrics[0].exceeded is True

    def test_concentration_risk_breach(self):
        engine = RiskEngine()
        inputs = RiskEngineInput(
            instrument_id=1,
            returns_by_instrument={
                1: _returns(30, seed=1),
                2: _returns(30, seed=2),
            },
            positions=(
                PortfolioPosition(instrument_id=1, sleeve_id="core", weight=0.85),
                PortfolioPosition(instrument_id=2, sleeve_id="core", weight=0.15),
            ),
            sector_by_instrument={1: "tech", 2: "tech"},
        )
        budget = _budget(diversification_policy={"max_pct_per_instrument": 50.0})
        assessment = engine.assess(inputs, budget)
        conc = next(m for m in assessment.metrics if m.name == "concentration_instrument")
        assert conc.value == pytest.approx(85.0)
        assert conc.exceeded is True

    def test_gap_risk_breach_on_synthetic_overnight_gaps(self):
        engine = RiskEngine()
        overnight = [0.001, -0.001, 0.12, -0.10, 0.09, -0.08, 0.001] * 4
        inputs = RiskEngineInput(
            instrument_id=201,
            returns_by_instrument={201: _returns(30, seed=5)},
            overnight_returns_by_instrument={201: overnight},
            asset_category=AssetCategory.EQUITIES,
        )
        budget = _budget(diversification_policy={"max_gap_risk_prob": 0.05})
        assessment = engine.assess(inputs, budget)
        inst = assessment.instrument_assessments[0]
        gap = next(m for m in inst.metrics if m.name == "gap_risk")
        assert gap.value > 0.05
        assert gap.exceeded is True

    def test_tail_risk_from_forecast_score(self):
        engine = RiskEngine()
        inputs = RiskEngineInput(
            instrument_id=101,
            returns_by_instrument={101: _returns(30, vol=0.001, seed=7)},
            tail_risk_score=0.92,
        )
        budget = _budget(diversification_policy={"max_tail_risk_score": 0.75})
        assessment = engine.assess(inputs, budget)
        inst = assessment.instrument_assessments[0]
        tail = next(m for m in inst.metrics if m.name == "tail_risk")
        assert tail.value == pytest.approx(0.92)
        assert tail.exceeded is True

    def test_event_risk_active_when_locked(self):
        engine = RiskEngine()
        inputs = RiskEngineInput(
            instrument_id=101,
            returns_by_instrument={101: _returns(20, seed=8)},
            active_lock_instrument_ids=frozenset({101}),
        )
        budget = _budget(diversification_policy={"max_event_risk": 0.0})
        assessment = engine.assess(inputs, budget)
        inst = assessment.instrument_assessments[0]
        event = next(m for m in inst.metrics if m.name == "event_risk")
        assert event.value == 1.0
        assert event.exceeded is True

    def test_correlation_cluster_weight(self):
        base = _returns(30, drift=0.001, vol=0.01, seed=10)
        returns = {
            1: base,
            2: [value * 0.98 + 0.0002 for value in base],
            3: _returns(30, drift=-0.002, vol=0.02, seed=12),
        }
        edges = tuple(build_correlation_edges(returns))
        positions = (
            PortfolioPosition(instrument_id=1, sleeve_id="core", weight=0.4),
            PortfolioPosition(instrument_id=2, sleeve_id="core", weight=0.35),
            PortfolioPosition(instrument_id=3, sleeve_id="def", weight=0.25),
        )
        weight = compute_correlation_cluster_weight(1, positions, edges, threshold=0.5)
        assert weight >= 0.70


class TestRiskGateRiskEngineIntegration:
    def test_risk_gate_blocks_on_var_breach(self):
        gate = RiskGate()
        volatile = _returns(60, vol=0.10, seed=99)
        risk_inputs = RiskEngineInput(
            instrument_id=101,
            returns_by_instrument={101: volatile},
            positions=(PortfolioPosition(instrument_id=101, sleeve_id="sleeve-1", weight=1.0),),
        )
        profile = _profile(
            diversification_policy={
                "max_correlation": 0.95,
                "max_correlation_cluster_pct": 100,
                "max_var_95": 0.001,
            },
        )
        result = gate.check_intent(
            _intent(),
            profile,
            _sleeve(),
            _context(),
            risk_inputs=risk_inputs,
        )
        assert result.allowed is False
        assert result.outcome == RiskGateOutcome.BLOCKED
        assert "RiskEngine" in result.reason
        assert "risk_assessment" in result.metadata

    def test_risk_gate_passes_with_neutral_metrics(self):
        gate = RiskGate()
        calm = _returns(40, vol=0.005, seed=20)
        risk_inputs = RiskEngineInput(
            instrument_id=101,
            returns_by_instrument={101: calm},
            positions=(PortfolioPosition(instrument_id=101, sleeve_id="sleeve-1", weight=0.5),),
            prices_by_instrument={101: [100.0 + i * 0.1 for i in range(40)]},
        )
        profile = _profile(
            diversification_policy={
                "max_correlation": 0.95,
                "max_correlation_cluster_pct": 100,
                "max_var_95": 0.50,
                "max_pct_per_instrument": 60,
            },
        )
        result = gate.check_intent(
            _intent(),
            profile,
            _sleeve(),
            _context(),
            risk_inputs=risk_inputs,
        )
        assert result.allowed is True
        assert "risk_assessment" in result.metadata

    def test_risk_gate_blocks_concentration_without_risk_inputs_still_passes(self):
        """RiskEngine checks are optional — no risk_inputs means legacy path."""
        gate = RiskGate()
        result = gate.check_intent(
            _intent(),
            _profile(diversification_policy={"max_correlation_cluster_pct": 100}),
            _sleeve(),
            _context(),
        )
        assert result.allowed is True
        assert "risk_assessment" not in result.metadata

    def test_gap_risk_blocks_via_risk_gate(self):
        gate = RiskGate()
        overnight = [0.001, -0.001, 0.12, -0.10, 0.09, -0.08, 0.001] * 6
        risk_inputs = RiskEngineInput(
            instrument_id=101,
            returns_by_instrument={101: _returns(30, vol=0.01, seed=3)},
            overnight_returns_by_instrument={101: overnight},
            asset_category=AssetCategory.EQUITIES,
        )
        profile = _profile(
            diversification_policy={
                "max_correlation_cluster_pct": 100,
                "max_gap_risk_prob": 0.05,
                "max_var_95": 0.50,
            },
        )
        result = gate.check_intent(
            _intent(),
            profile,
            _sleeve(),
            _context(),
            risk_inputs=risk_inputs,
        )
        assert result.allowed is False
        assert result.metadata.get("risk_metric") == "gap_risk"
