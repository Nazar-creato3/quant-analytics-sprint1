"""Marginal risk mandatory gate tests."""
from __future__ import annotations

from dataclasses import replace

from app.services.approval.engine import evaluate_policy
from app.tests.test_approval_policy_engine import _context, _intent, _profile


def test_sizing_intent_without_marginal_risk_holds_for_review():
    intent = _intent().model_copy(update={"exit_logic": {"position_size_usd": 5000}})
    decision = evaluate_policy(intent, _profile(), _context())
    assert decision.state.value == "hold_for_review"
    assert "Marginal risk" in decision.reason


def test_marginal_risk_computed_allows_policy_evaluation():
    intent = _intent().model_copy(update={"exit_logic": {"position_size_usd": 5000}})
    ctx = replace(_context(), marginal_risk_computed=True, proposed_delta_var=0.01)
    decision = evaluate_policy(intent, _profile(), ctx)
    assert "Marginal risk" not in decision.reason
