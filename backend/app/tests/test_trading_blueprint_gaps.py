"""Trading placement audit + watchlist alert evaluation tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.compliance.trading_placement_audit import resolve_broker_mode


def test_resolve_broker_mode_paper_sim():
    assert resolve_broker_mode(live_unlocked=False, paper_sim=True) == "paper_sim"


def test_resolve_broker_mode_live():
    assert resolve_broker_mode(live_unlocked=True, paper_sim=False) == "live"


@pytest.mark.asyncio
async def test_watchlist_alert_triggers_on_threshold():
    from datetime import datetime, timezone

    from app.db.models import WatchlistAlertRule
    from app.services.alerts.watchlist_rules import evaluate_watchlist_alert_rules

    rule = WatchlistAlertRule(
        id="r1",
        user_email="u@test.com",
        symbol="AAPL",
        metric="ml_confidence",
        threshold=0.6,
        direction="above",
        enabled=True,
    )

    class _Scalars:
        def all(self):
            return [rule]

    class _Result:
        def scalars(self):
            return _Scalars()

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result())
    session.commit = AsyncMock()

    with patch(
        "app.services.alerts.watchlist_rules._metric_value",
        new=AsyncMock(return_value=0.75),
    ):
        with patch(
            "app.services.alerts.watchlist_rules.emit_ops_alert",
            new=AsyncMock(),
        ) as emit:
            stats = await evaluate_watchlist_alert_rules(session)

    assert stats["triggered"] == 1
    emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_maneuver_generator_uses_hierarchy_interval():
    from types import SimpleNamespace

    from app.services.risk.maneuver_generator import ManeuverGenerator, ManeuverCandidate
    from app.services.ml.model import ModelPrediction
    from app.services.risk.engine import TradeRiskResult

    interval = SimpleNamespace(
        horizon_days=10,
        p10=-0.04,
        p90=0.04,
        rolling_volatility=0.02,
        confidence_multiplier=1.645,
    )
    gen = ManeuverGenerator(portfolio_size=10_000, confidence_threshold=0.5)
    pred = ModelPrediction(
        ticker="TEST",
        direction="long",
        confidence=0.8,
        raw_score=0.8,
        signal_strength=0.5,
        features_used={},
        model_version="test",
    )
    risk = TradeRiskResult(
        ticker="TEST",
        direction="long",
        is_tradeable=True,
        reason="ok",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        position_size_usd=1000.0,
        risk_percent=1.0,
        risk_reward_ratio=2.0,
    )
    cand = ManeuverCandidate(
        ticker="TEST",
        prediction=pred,
        risk=risk,
        time_horizon="3–5 дней",
    )
    out = gen._candidate_to_output(cand, rank=1, interval_forecast=interval)
    assert out.expected_pnl_low is not None
    assert "Модельный диапазон" in out.execution_plan
