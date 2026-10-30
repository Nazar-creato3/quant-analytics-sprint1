"""Prompt 90 — poll tradeable_count must match report GET and list semantics."""
from __future__ import annotations

from types import SimpleNamespace

from app.schemas.schemas import StrategyType
from app.services.pipeline.maneuver_counts import (
    analysis_list_counts_sync,
    count_tradeable_persisted,
)


def _row(
    strategy: str,
    ticker: str = "AAPL",
    direction: str = "long",
    position_size_usd: float | None = 1_000.0,
):
    return SimpleNamespace(
        strategy_type=strategy,
        ticker=ticker,
        direction=direction,
        position_size_usd=position_size_usd,
    )


def test_maneuvers_count_toast_vs_list_sync():
    maneuvers = [
        _row(StrategyType.TREND_FOLLOWING.value, "AAPL"),
        _row(StrategyType.NO_TRADE.value, "—", "neutral"),
    ]
    persisted = count_tradeable_persisted(maneuvers)
    assert persisted == 1
    assert analysis_list_counts_sync(
        status_tradeable=1,
        report_maneuvers=maneuvers,
        list_tradeable=1,
    )
    assert not analysis_list_counts_sync(
        status_tradeable=10,
        report_maneuvers=maneuvers,
        list_tradeable=1,
    )


def test_zero_sized_directional_rows_are_not_tradeable():
    maneuvers = [
        _row(StrategyType.MOMENTUM.value, "SPY", "long", 0.0),
        _row(StrategyType.TREND_FOLLOWING.value, "QQQ", "short", None),
        _row(StrategyType.MOMENTUM.value, "BTC-USD", "long", 500.0),
    ]

    assert count_tradeable_persisted(maneuvers) == 1
    assert analysis_list_counts_sync(
        status_tradeable=1,
        report_maneuvers=maneuvers,
        list_tradeable=1,
    )


def test_diagnostics_golden_maneuvers_count_toast_vs_list_sync():
    from app.services.diagnostics.engine import golden_maneuvers_count_toast_vs_list_sync

    finding = golden_maneuvers_count_toast_vs_list_sync()
    assert finding.check_id == "maneuvers_count_toast_vs_list_sync"
    assert finding.passed
