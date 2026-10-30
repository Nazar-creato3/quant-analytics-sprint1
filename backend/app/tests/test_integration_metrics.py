"""Unit tests for integration metrics helpers."""
from __future__ import annotations

from app.domain.enums import Strategy
from app.services.integration.metrics import (
    build_equity_curve,
    compute_max_drawdown_pct,
    compute_sharpe_ratio,
    compute_win_rate,
)
from app.services.integration.types import PaperTrade


def _trade(return_pct: float) -> PaperTrade:
    return PaperTrade(
        intent_id="t1",
        strategy=Strategy.TREND,
        symbol="BTC-USD",
        entry_price=100.0,
        exit_price=100.0 + return_pct,
        return_pct=return_pct,
        entry_ts="2026-01-01T00:00:00+00:00",
        exit_ts="2026-01-02T00:00:00+00:00",
    )


class TestIntegrationMetrics:
    def test_win_rate(self):
        trades = [_trade(1.0), _trade(-0.5), _trade(2.0)]
        assert compute_win_rate(trades) == round(2 / 3, 4)

    def test_max_drawdown(self):
        curve, _ = build_equity_curve([_trade(5.0), _trade(-10.0), _trade(2.0)])
        dd = compute_max_drawdown_pct(curve)
        assert dd > 0.0

    def test_sharpe_with_returns(self):
        trades = [_trade(1.0)] * 10 + [_trade(-0.5)] * 10
        _, returns = build_equity_curve(trades)
        sharpe = compute_sharpe_ratio(returns)
        assert isinstance(sharpe, float)
