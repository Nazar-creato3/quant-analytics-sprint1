"""Tests for Prompt 28 ExplainabilityLayer."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.control_fabric.audit_journal import ControlFabricAuditAction
from app.services.control_fabric.risk_types import (
    InstrumentRiskAssessment,
    PortfolioRiskAssessment,
    RiskMetricAssessment,
)
from app.services.explainability import ExplainabilityLayer
from app.services.explainability.formatters import fmt_num, fmt_pct, fmt_pct_change
from app.services.forecast import ForecastDirection, ForecastSignals, aggregate_forecast


def _audit_entry(*, action: str, details: dict) -> _FakeAuditLog:
    return _FakeAuditLog(action=action, details=details)


class _FakeAuditLog:
    def __init__(self, *, action: str, details: dict) -> None:
        self.action = action
        self.details = details
        self.timestamp = datetime(2026, 7, 18, tzinfo=timezone.utc)
        self.error = None


class TestExplainabilityFormatters:
    def test_pct_change_matches_inputs(self):
        assert fmt_pct_change(0.5, 0.7) == "+40.0%"
        assert fmt_num(0.3, decimals=2) == "0.30"
        assert fmt_pct(0.7, decimals=1) == "70.0%"


class TestRegimeExplainability:
    def test_regime_transition_cites_volatility_and_r_squared(self):
        layer = ExplainabilityLayer()
        text, metrics = layer.explain_regime_transition(
            previous_regime="bullish_trend",
            current_regime="choppy_range",
            confidence=0.71,
            features={"vol_ratio": 1.4},
            prior_features={"vol_ratio": 1.0},
            factor_r_squared_current=0.3,
            factor_r_squared_previous=0.7,
        )
        assert "bullish trend" in text
        assert "choppy range" in text
        assert "0.71" in text
        assert "+40.0%" in text
        assert "1.00" in text and "1.40" in text
        assert "0.70" in text and "0.30" in text
        assert metrics["vol_ratio"] == 1.4
        assert metrics["r_squared_previous"] == 0.7


class TestFactorExplainability:
    def test_factor_model_cites_r_squared_and_dominant_beta(self):
        layer = ExplainabilityLayer()
        text, metrics = layer.explain_factor_model(
            r_squared=0.42,
            prior_r_squared=0.58,
            betas={"market_beta": 0.82, "sector_factor": 0.15},
        )
        assert "42.0%" in text
        assert "0.58" in text and "0.42" in text
        assert "market beta" in text
        assert "0.82" in text
        assert metrics["dominant_factor"] == "market_beta"


class TestForecastExplainability:
    def test_forecast_cites_confidence_and_risk_flags(self):
        layer = ExplainabilityLayer()
        forecast = aggregate_forecast(
            instrument_id=1,
            regime_distribution={"choppy_range": 0.6, "bullish_trend": 0.4},
            regime_confidence=0.77,
            signals=ForecastSignals(
                short_term_momentum=0.12,
                momentum_direction=ForecastDirection.NEUTRAL,
                tail_risk_score=0.81,
                volatility_expansion_probability=0.74,
                correlation_shift_score=0.2,
                liquidity_deterioration_score=0.1,
                event_impact_score=0.05,
            ),
            risk_flag_threshold=0.65,
            elevated_uncertainty_threshold=0.55,
        )
        text, metrics = layer.explain_forecast(forecast)
        assert fmt_num(forecast.confidence, decimals=2) in text
        assert fmt_num(forecast.composite_risk_score, decimals=2) in text
        assert "tail_risk" in text or "volatility_expansion" in text
        assert metrics["confidence"] == pytest.approx(forecast.confidence)


class TestRiskExplainability:
    def test_risk_assessment_cites_breach_values(self):
        layer = ExplainabilityLayer()
        assessment = PortfolioRiskAssessment(
            metrics=(
                RiskMetricAssessment(
                    name="var_95",
                    value=0.082,
                    threshold=0.05,
                    exceeded=True,
                    scope="portfolio",
                ),
            ),
            instrument_assessments=(
                InstrumentRiskAssessment(
                    instrument_id=7,
                    metrics=(
                        RiskMetricAssessment(
                            name="tail_risk",
                            value=0.91,
                            threshold=0.75,
                            exceeded=True,
                            scope="instrument",
                        ),
                    ),
                ),
            ),
        )
        text, metrics = layer.explain_risk_assessment(assessment)
        assert "0.0820" in text
        assert "0.0500" in text
        assert metrics["breached_count"] == 2


class TestAuditExplainability:
    def test_risk_gate_audit_uses_metadata_numbers(self):
        layer = ExplainabilityLayer()
        entry = _audit_entry(
            action=ControlFabricAuditAction.RISK_GATE,
            details={
                "outcome": "blocked",
                "allowed": False,
                "reason": "RiskEngine var_95 exceeded",
                "metadata": {
                    "risk_metric": "var_95",
                    "risk_value": 0.082,
                    "risk_threshold": 0.05,
                    "risk_scope": "portfolio",
                },
            },
        )
        explanation = layer.explain_audit_entry(entry)
        assert explanation.decision_type == "risk_gate"
        assert "0.0820" in explanation.text
        assert "0.0500" in explanation.text
        assert explanation.source_metrics["risk_metric"] == "var_95"

    def test_approval_audit_cites_policy_state_and_risk_score(self):
        layer = ExplainabilityLayer()
        entry = _audit_entry(
            action="approval_policy.hold_for_review",
            details={
                "policy_state": "hold_for_review",
                "reason": "volatility above sleeve tolerance",
                "risk_score": 0.63,
            },
        )
        explanation = layer.explain_audit_entry(entry)
        assert "0.63" in explanation.text
        assert "hold_for_review" in explanation.text
        assert "volatility above sleeve tolerance" in explanation.text
