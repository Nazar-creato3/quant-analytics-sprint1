"""Tests for production fixes — approval, audit, backtest analysis, news, grid tick."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.approval.deal_intent_ops import (
    DealIntentOperationError,
    approve_deal_intent,
    reject_deal_intent,
)
from app.services.backtest_analysis.classifier import (
    ExitClassification,
    classify_trade_exit,
    classify_trade_log,
    filter_clean_trades,
)
from app.services.backtest_analysis.weekly import aggregate_runs, build_weekly_report
from app.services.grid.tick import apply_price_tick
from app.services.news.filtering import compute_market_relevance, is_market_relevant


class TestTradeClassifier:
    def test_clean_exit_reasons(self):
        assert classify_trade_exit("rsi_overbought") == ExitClassification.CLEAN_EXIT
        assert classify_trade_exit("mid_bb") == ExitClassification.CLEAN_EXIT
        assert classify_trade_exit("end_of_data") == ExitClassification.CLEAN_EXIT

    def test_non_clean_exit_reasons(self):
        assert classify_trade_exit("stop_loss") == ExitClassification.NON_CLEAN_EXIT
        assert classify_trade_exit("kill_switch") == ExitClassification.NON_CLEAN_EXIT
        assert classify_trade_exit("manual_panic") == ExitClassification.NON_CLEAN_EXIT

    def test_filter_clean_trades(self):
        trades = [
            {"exit_reason": "rsi_overbought", "pnl": 10},
            {"exit_reason": "stop_loss", "pnl": -5},
        ]
        clean = filter_clean_trades(trades)
        assert len(clean) == 1
        assert clean[0]["exit_classification"] == ExitClassification.CLEAN_EXIT.value


class TestWeeklyAggregation:
    def test_aggregate_runs_reproducible_hash(self):
        run = MagicMock()
        run.status = "complete"
        run.strategy = "momentum_ml"
        run.ticker = "AAPL"
        run.id = "run-1"
        run.total_return_pct = 5.0
        run.trade_log = [{"exit_reason": "rsi_overbought", "pnl": 1, "entry_date": "2025-01-01", "exit_date": "2025-01-03"}]
        run.equity_curve = [{"equity": 100000}, {"equity": 105000}]
        run.metrics = {}
        run.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        report_a = aggregate_runs([run], clean_only=True)
        report_b = aggregate_runs([run], clean_only=True)
        assert report_a["reproducibility_hash"] == report_b["reproducibility_hash"]
        assert report_a["clean_trade_count"] == 1

    @pytest.mark.asyncio
    async def test_build_weekly_report_empty(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        report = await build_weekly_report(db, days=7)
        assert report["kind"] == "weekly_backtest_analysis"
        assert "week_label" in report


class TestNewsFiltering:
    def test_excludes_local_crime(self):
        text = "Wildberries уголовное дело и дрон над городом"
        assert is_market_relevant(text) is False
        assert compute_market_relevance(text) == 0.0

    def test_includes_macro(self):
        text = "Fed raises interest rates amid inflation concerns"
        assert is_market_relevant(text) is True
        assert compute_market_relevance(text) >= 0.15

    def test_includes_earnings(self):
        text = "AAPL beats earnings forecast with strong revenue growth"
        assert is_market_relevant(text, "AAPL") is True

    def test_includes_russian_macro(self):
        text = "ЦБ РФ сохранил ключевую ставку; инфляция замедляется, рынок акций вырос"
        assert is_market_relevant(text) is True
        assert compute_market_relevance(text) >= 0.15

    def test_trusted_rss_source(self):
        from app.services.news.filtering import is_trusted_rss_source

        assert is_trusted_rss_source("rbc") is True
        assert is_trusted_rss_source("unknown") is False


class TestGridTick:
    def test_apply_price_tick_buy_fill(self):
        data = {
            "config": {
                "ticker": "AAPL",
                "lower_price": 170,
                "upper_price": 200,
                "grid_count": 5,
                "total_capital": 10000,
                "entry_price": 185,
            },
            "summary": {"last_price": 185.0, "ticker": "AAPL"},
            "levels": [
                {"price": 180.0, "side": "buy", "quantity": 10, "status": "pending", "fill_price": None, "pnl": 0},
            ],
            "realized_pnl": 0.0,
            "total_trades": 0,
            "is_active": True,
        }
        updated = apply_price_tick(data, 179.0)
        filled = [l for l in updated["levels"] if l["status"] == "filled"]
        assert updated["total_trades"] == 1
        assert len(filled) == 1


class TestDealIntentOps:
    @pytest.mark.asyncio
    async def test_approve_pending_intent(self):
        from app.domain.deal_intent_enums import DealIntentStatus

        intent = MagicMock()
        intent.id = "intent-1"
        intent.status = DealIntentStatus.PENDING_APPROVAL.value
        intent.exit_logic = {}
        intent.updated_at = None

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=intent)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            ]
        )
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with patch("app.services.approval.deal_intent_ops._notify"):
            result = await approve_deal_intent(db, "intent-1", "op@test.com")
        assert result.status_after == DealIntentStatus.APPROVED.value

    @pytest.mark.asyncio
    async def test_reject_wrong_status_raises(self):
        intent = MagicMock()
        intent.status = "filled"
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=intent)))
        with pytest.raises(DealIntentOperationError):
            await reject_deal_intent(db, "intent-1", "op@test.com")
