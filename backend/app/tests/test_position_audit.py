"""Tests for position audit pipeline modules."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.audit.core_stats import compute_core_stats
from app.services.audit.execution_quality import compute_execution_quality
from app.services.audit.expiration_analysis import compute_expiration_analysis
from app.services.audit.factor_attribution import compute_factor_attribution
from app.services.audit.pattern_analysis import compute_pattern_analysis
from app.services.audit.r_multiple import compute_r_multiple, compute_r_multiple_stats
from app.services.audit.streak_analysis import compute_monte_carlo_bust, compute_streak_analysis
from app.services.audit.types import ClosedTradeRecord
from app.services.audit.user_summary import build_user_summary
from app.services.portfolio.entry_snapshot import update_peak_unrealized


def _trade(
    idx: int,
    *,
    pnl: float,
    ticker: str = "AAPL",
    exit_reason: str = "expiration",
    peak: float | None = None,
    factor: str = "momentum",
) -> ClosedTradeRecord:
    entry = 100.0
    stop = 95.0
    return ClosedTradeRecord(
        id=f"t-{idx}",
        ticker=ticker,
        strategy_type="momentum",
        direction="long",
        entry_price=entry,
        stop_loss_price=stop,
        position_size_usd=1000.0,
        fill_price=entry,
        exit_price=entry + pnl / 10.0,
        realized_pnl=pnl,
        exit_reason=exit_reason,
        signal_generated_price=entry - 0.5,
        peak_unrealized_pnl=peak,
        factor_exposures={factor: 0.8, "value": 0.1},
        regime_at_entry="bullish_trend",
        sector_at_entry="technology",
        filled_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        closed_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        hold_duration_seconds=172_800.0,
    )


def test_core_stats_on_sample_trades():
    trades = [_trade(i, pnl=50.0 if i % 2 == 0 else -20.0) for i in range(8)]
    stats = compute_core_stats(trades)
    assert stats["trade_count"] == 8
    assert 0.0 < stats["win_rate"] < 1.0
    assert stats["expectancy"] != 0.0
    assert "sharpe" in stats
    assert "max_drawdown" in stats


def test_r_multiple_computation():
    trade = _trade(1, pnl=100.0)
    assert trade.position_size == trade.position_size_usd
    r = compute_r_multiple(trade)
    assert r is not None
    assert r > 0
    stats = compute_r_multiple_stats([trade, _trade(2, pnl=-50.0)])
    assert stats["count"] == 2
    assert stats["mean_r"] is not None


def test_factor_attribution_groups():
    trades = [
        _trade(1, pnl=30.0, factor="momentum"),
        _trade(2, pnl=-10.0, factor="momentum"),
        _trade(3, pnl=20.0, factor="value"),
    ]
    result = compute_factor_attribution(trades)
    assert "momentum" in result["by_dominant_factor"]
    assert "value" in result["by_dominant_factor"]


def test_pattern_analysis_dimensions():
    trades = [
        _trade(1, pnl=10.0, ticker="AAPL"),
        _trade(2, pnl=-5.0, ticker="MSFT"),
    ]
    result = compute_pattern_analysis(trades)
    assert "AAPL" in result["by_ticker"]
    assert "technology" in result["by_sector"]
    assert "bullish_trend" in result["by_regime"]


def test_expiration_analysis_left_on_table():
    trades = [
        _trade(1, pnl=50.0, peak=120.0, exit_reason="expiration"),
        _trade(2, pnl=30.0, peak=40.0, exit_reason="expiration"),
    ]
    result = compute_expiration_analysis(trades)
    assert result["expiration_trade_count"] == 2
    assert result["avg_left_on_table_usd"] > 0
    assert result["avg_left_on_table_pct_of_realized_profit"] > 0


def test_execution_quality_slippage():
    trades = [_trade(i, pnl=10.0) for i in range(5)]
    result = compute_execution_quality(trades)
    assert result["count"] == 5
    assert result["mean_slippage"] is not None


def test_streak_and_monte_carlo():
    trades = [_trade(i, pnl=20.0 if i < 3 else -15.0) for i in range(6)]
    streaks = compute_streak_analysis(trades)
    assert streaks["longest_winning_streak"] >= 1
    mc = compute_monte_carlo_bust(trades, simulations=100)
    assert mc["simulations"] == 100
    assert mc["bust_probability"] is not None


def test_user_summary_simple():
    trades = [
        _trade(1, pnl=100.0, ticker="AAPL"),
        _trade(2, pnl=-30.0, ticker="MSFT"),
        _trade(3, pnl=50.0, ticker="AAPL"),
    ]
    summary = build_user_summary(trades, most_common_maneuver="momentum")
    assert summary["total_pnl_usd"] == 120.0
    assert summary["win_rate"] > 0
    assert len(summary["top_tickers"]) <= 3
    assert summary["most_common_maneuver"] == "momentum"


def test_update_peak_unrealized():
    m = MagicMock()
    m.peak_unrealized_pnl = None
    assert update_peak_unrealized(m, 50.0) is True
    assert m.peak_unrealized_pnl == 50.0
    assert update_peak_unrealized(m, 40.0) is False


@pytest.mark.asyncio
async def test_audit_status_insufficient_count():
    from app.api.v1.endpoints.position_audit import get_audit_status

    user = MagicMock(id="user-1")
    db = AsyncMock()

    with patch(
        "app.api.v1.endpoints.position_audit.get_user_by_email",
        AsyncMock(return_value=user),
    ):
        with patch(
            "app.api.v1.endpoints.position_audit.close_expired_for_user",
            AsyncMock(return_value={"closed": 0}),
        ):
            with patch(
                "app.api.v1.endpoints.position_audit.count_expiration_closes_since_last_audit",
                AsyncMock(return_value=(0, None)),
            ):
                with patch(
                    "app.api.v1.endpoints.position_audit.has_running_audit",
                    AsyncMock(return_value=False),
                ):
                    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
                    result = await get_audit_status(email="u@test.com", db=db)

    assert result["expiration_close_count"] == 0
    assert result["ready_to_trigger"] is False
    assert "Нет новых закрыт" in result["message_ru"]


@pytest.mark.asyncio
async def test_trigger_enqueues_when_threshold_met():
    from app.api.v1.endpoints.position_audit import trigger_audit

    user = MagicMock(id="user-1")
    audit = MagicMock(id="audit-1")
    db = AsyncMock()
    db.commit = AsyncMock()

    with patch(
        "app.api.v1.endpoints.position_audit.get_user_by_email",
        AsyncMock(return_value=user),
    ):
        with patch(
            "app.api.v1.endpoints.position_audit.close_expired_for_user",
            AsyncMock(return_value={"closed": 0}),
        ):
            with patch(
                "app.api.v1.endpoints.position_audit.count_expiration_closes_since_last_audit",
                AsyncMock(return_value=(100, None)),
            ):
                with patch(
                    "app.api.v1.endpoints.position_audit.has_running_audit",
                    AsyncMock(return_value=False),
                ):
                    with patch(
                        "app.api.v1.endpoints.position_audit.try_enqueue_position_audit",
                        AsyncMock(return_value=audit),
                    ):
                        with patch("app.api.v1.endpoints.position_audit.run_position_audit_task") as mock_task:
                            mock_task.delay = MagicMock()
                            result = await trigger_audit(email="u@test.com", db=db)

    assert result["status"] == "queued"
    assert result["audit_id"] == "audit-1"
    mock_task.delay.assert_called_once_with("audit-1")


@pytest.mark.asyncio
async def test_trigger_does_not_enqueue_partial_audit():
    from app.api.v1.endpoints.position_audit import trigger_audit

    user = MagicMock(id="user-1")
    db = AsyncMock()

    with patch(
        "app.api.v1.endpoints.position_audit.get_user_by_email",
        AsyncMock(return_value=user),
    ):
        with patch(
            "app.api.v1.endpoints.position_audit.close_expired_for_user",
            AsyncMock(return_value={"closed": 0}),
        ):
            with patch(
                "app.api.v1.endpoints.position_audit.count_expiration_closes_since_last_audit",
                AsyncMock(return_value=(0, None)),
            ):
                with patch("app.api.v1.endpoints.position_audit.run_position_audit_task") as mock_task:
                    mock_task.delay = MagicMock()
                    result = await trigger_audit(email="u@test.com", db=db)

    assert result["status"] == "insufficient"
    assert result["expiration_close_count"] == 0
    mock_task.delay.assert_not_called()


def test_position_audit_task_routes_to_pipeline_queue():
    from app.tasks.celery_app import celery_app

    route = celery_app.conf.task_routes["app.tasks.position_audit.*"]
    assert route["queue"] == "celery"


@pytest.mark.asyncio
async def test_try_enqueue_position_audit_at_batch_size():
    from app.services.audit.repository import AUDIT_BATCH_SIZE, audit_ready, try_enqueue_position_audit

    assert audit_ready(AUDIT_BATCH_SIZE)
    assert not audit_ready(AUDIT_BATCH_SIZE - 1)

    db = AsyncMock()
    db.flush = AsyncMock()
    audit_row = MagicMock(id="audit-1", trade_count=AUDIT_BATCH_SIZE)

    with patch(
        "app.services.audit.repository.has_running_audit",
        AsyncMock(return_value=False),
    ):
        with patch(
            "app.services.audit.repository.count_expiration_closes_since_last_audit",
            AsyncMock(return_value=(AUDIT_BATCH_SIZE, None)),
        ):
            with patch(
                "app.services.audit.repository.create_audit_run",
                AsyncMock(return_value=audit_row),
            ):
                audit = await try_enqueue_position_audit(db, "user-1")

    assert audit is audit_row


@pytest.mark.asyncio
async def test_get_audit_status_auto_enqueues_at_threshold():
    from app.api.v1.endpoints.position_audit import get_audit_status

    user = MagicMock(id="user-1")
    audit = MagicMock(id="audit-auto")
    db = AsyncMock()
    db.commit = AsyncMock()

    with patch(
        "app.api.v1.endpoints.position_audit.get_user_by_email",
        AsyncMock(return_value=user),
    ):
        with patch(
            "app.api.v1.endpoints.position_audit.close_expired_for_user",
            AsyncMock(return_value={"closed": 0}),
        ):
            with patch(
                "app.api.v1.endpoints.position_audit.count_expiration_closes_since_last_audit",
                AsyncMock(return_value=(100, None)),
            ):
                with patch(
                    "app.api.v1.endpoints.position_audit.has_running_audit",
                    AsyncMock(return_value=False),
                ):
                    with patch(
                        "app.api.v1.endpoints.position_audit.try_enqueue_position_audit",
                        AsyncMock(return_value=audit),
                    ):
                        with patch(
                            "app.api.v1.endpoints.position_audit.run_position_audit_task"
                        ) as mock_task:
                            mock_task.delay = MagicMock()
                            db.execute = AsyncMock(
                                return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
                            )
                            result = await get_audit_status(email="u@test.com", db=db)

    assert result["expiration_close_count"] == 100
    assert result["audit_running"] is True
    mock_task.delay.assert_called_once_with("audit-auto")


@pytest.mark.asyncio
async def test_enqueue_position_audits_for_users():
    from app.services.portfolio.audit_trigger import enqueue_position_audits_for_users

    db = AsyncMock()
    db.commit = AsyncMock()
    audit = MagicMock(id="audit-2")

    with patch(
        "app.services.portfolio.audit_trigger.try_enqueue_position_audit",
        AsyncMock(return_value=audit),
    ):
        with patch("app.tasks.position_audit.run_position_audit_task") as mock_task:
            mock_task.delay = MagicMock()
            triggered = await enqueue_position_audits_for_users(db, {"user-1"})

    assert triggered == ["audit-2"]
    mock_task.delay.assert_called_once_with("audit-2")


@pytest.mark.asyncio
async def test_expiration_close_count_uses_unlimited_db_count():
    from app.services.audit.repository import count_expiration_closes_since_last_audit

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=150)))

    with patch("app.services.audit.repository.last_completed_audit", AsyncMock(return_value=None)):
        count, watermark = await count_expiration_closes_since_last_audit(db, "user-1")

    count_stmt = db.execute.call_args.args[0]
    assert count == 150
    assert watermark is None
    assert "LIMIT" not in str(count_stmt).upper()


@pytest.mark.asyncio
async def test_audit_completion_does_not_delete_closed_trades(tmp_path):
    from app.services.audit.pipeline import run_position_audit

    audit = SimpleNamespace(
        id="audit-1",
        user_id="user-1",
        trade_count=100,
        status="pending",
        started_at=None,
        completed_at=None,
        error_message=None,
        admin_metrics=None,
        user_summary=None,
        report_path=None,
    )
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=audit)))
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    trades = [_trade(i, pnl=10.0 if i % 2 == 0 else -5.0) for i in range(100)]

    with patch("app.services.audit.pipeline.fetch_audit_trades", AsyncMock(return_value=trades)):
        with patch("app.services.audit.pipeline.compute_core_stats", return_value={"trade_count": 100}):
            with patch("app.services.audit.pipeline.compute_r_multiple_stats", return_value={}):
                with patch("app.services.audit.pipeline.compute_factor_attribution", return_value={}):
                    with patch("app.services.audit.pipeline.compute_pattern_analysis", return_value={}):
                        with patch("app.services.audit.pipeline.compute_expiration_analysis", return_value={}):
                            with patch("app.services.audit.pipeline.compute_execution_quality", return_value={}):
                                with patch("app.services.audit.pipeline.compute_streak_analysis", return_value={}):
                                    with patch("app.services.audit.pipeline.compute_monte_carlo_bust", return_value={}):
                                        with patch(
                                            "app.services.audit.pipeline.resolve_most_common_maneuver",
                                            AsyncMock(return_value="momentum"),
                                        ):
                                            with patch(
                                                "app.services.audit.pipeline.build_user_summary",
                                                return_value={"total_pnl_usd": 250.0},
                                            ):
                                                with patch(
                                                    "app.services.audit.pipeline.generate_tear_sheet",
                                                    return_value=tmp_path / "audit.html",
                                                ):
                                                    with patch(
                                                        "app.services.audit.pipeline._notify_admin",
                                                        AsyncMock(),
                                                    ):
                                                        result = await run_position_audit(db, "audit-1")

    assert result["status"] == "complete"
    assert audit.status == "complete"
    assert audit.trade_count == 100
    db.delete.assert_not_called()


def test_tear_sheet_writes_file(tmp_path):
    from app.services.audit.tear_sheet import generate_tear_sheet

    trades = [_trade(i, pnl=10.0) for i in range(5)]
    metrics = {"core_stats": compute_core_stats(trades)}
    with patch("app.services.audit.tear_sheet.REPORTS_DIR", tmp_path):
        path = generate_tear_sheet(trades, metrics, audit_id="test-audit")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Position Audit Report" in content
    assert "Core Performance" in content
