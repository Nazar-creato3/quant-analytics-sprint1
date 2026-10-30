"""Unit tests for execution guard — no direct broker bypass."""
from __future__ import annotations

import pytest

from app.domain.deal_intent_enums import DealIntentStatus
from app.services.execution.adapter import OrderRequest, PaperExecutor
from app.services.execution.guard import (
    DealIntentExecutionContext,
    DirectOrderBypassError,
    ExecutionGate,
)


class TestExecutionGate:
    def test_requires_context(self):
        with pytest.raises(DirectOrderBypassError):
            ExecutionGate.require_executing_intent(None)

    def test_requires_deal_intent_id(self):
        ctx = DealIntentExecutionContext(deal_intent_id="", status=DealIntentStatus.EXECUTING)
        with pytest.raises(DirectOrderBypassError, match="deal_intent_id"):
            ExecutionGate.require_executing_intent(ctx)

    @pytest.mark.parametrize(
        "status",
        [
            DealIntentStatus.DRAFT,
            DealIntentStatus.PENDING_APPROVAL,
            DealIntentStatus.APPROVED,
            DealIntentStatus.HELD,
            DealIntentStatus.FILLED,
            DealIntentStatus.REJECTED,
            DealIntentStatus.CANCELLED,
            DealIntentStatus.FAILED,
        ],
    )
    def test_rejects_non_executing_status(self, status: DealIntentStatus):
        ctx = DealIntentExecutionContext(deal_intent_id="intent-abc", status=status)
        with pytest.raises(DirectOrderBypassError, match="executing"):
            ExecutionGate.require_executing_intent(ctx)

    def test_allows_executing_status(self):
        ctx = DealIntentExecutionContext(
            deal_intent_id="intent-abc",
            status=DealIntentStatus.EXECUTING,
        )
        ExecutionGate.require_executing_intent(ctx)

    def test_allows_maneuver_context(self):
        from app.services.execution.guard import ManeuverExecutionContext

        ExecutionGate.require_executing_intent(
            None,
            maneuver_context=ManeuverExecutionContext(maneuver_id="m-1", status="approved"),
        )

    def test_allows_manual_order_context(self):
        from app.services.execution.guard import ManualOrderExecutionContext

        ExecutionGate.require_executing_intent(
            None,
            manual_order_context=ManualOrderExecutionContext(manual_order_id="ord-1"),
        )

    def test_context_from_status(self):
        ctx = ExecutionGate.context_from_status("intent-1", DealIntentStatus.EXECUTING)
        assert ctx.deal_intent_id == "intent-1"
        assert ctx.status == DealIntentStatus.EXECUTING


class TestPaperExecutorGuard:
    @pytest.mark.asyncio
    async def test_submit_without_context_raises(self):
        executor = PaperExecutor()
        req = OrderRequest(ticker="AAPL", side="buy", qty=1.0, order_type="market")
        with pytest.raises(DirectOrderBypassError):
            await executor.submit_order(req)

    @pytest.mark.asyncio
    async def test_submit_with_executing_context_allowed(self, monkeypatch):
        async def fake_quote(_ticker: str):
            return {"price": 100.0}

        monkeypatch.setattr(
            "app.services.market_data.client.get_latest_quote_resolved",
            fake_quote,
        )
        executor = PaperExecutor()
        req = OrderRequest(
            ticker="AAPL",
            side="buy",
            qty=1.0,
            order_type="market",
            execution_context=DealIntentExecutionContext(
                deal_intent_id="intent-xyz",
                status=DealIntentStatus.EXECUTING,
            ),
        )
        result = await executor.submit_order(req)
        assert result.status == "filled"
        assert result.broker_order_id is not None

    @pytest.mark.asyncio
    async def test_submit_with_manual_order_context_allowed(self, monkeypatch):
        async def fake_quote(_ticker: str):
            return {"price": 100.0}

        monkeypatch.setattr(
            "app.services.market_data.client.get_latest_quote_resolved",
            fake_quote,
        )
        from app.services.execution.guard import ManualOrderExecutionContext

        executor = PaperExecutor()
        req = OrderRequest(
            ticker="AAPL",
            side="buy",
            qty=1.0,
            order_type="market",
            manual_order_context=ManualOrderExecutionContext(manual_order_id="mo-1"),
        )
        result = await executor.submit_order(req)
        assert result.status == "filled"

    @pytest.mark.asyncio
    async def test_submit_with_approved_context_blocked(self):
        executor = PaperExecutor()
        req = OrderRequest(
            ticker="AAPL",
            side="buy",
            qty=1.0,
            order_type="market",
            execution_context=DealIntentExecutionContext(
                deal_intent_id="intent-xyz",
                status=DealIntentStatus.APPROVED,
            ),
        )
        with pytest.raises(DirectOrderBypassError):
            await executor.submit_order(req)
