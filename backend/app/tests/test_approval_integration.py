"""Integration tests for approval context builder and orchestrator."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.deal_intent_enums import DealIntentStatus, RiskTag
from app.domain.enums import AssetCategory, SleeveStatus
from app.services.approval.context import MarketContextBuilder, realized_volatility, spread_bps
from app.services.approval.models import MarketContext, PolicyDecision, PolicyState
from app.services.approval.orchestrator import ApprovalOrchestrator
from app.services.approval.service import ApprovalPolicyEngine
from app.tests.test_approval_policy_engine import _context, _intent, _profile

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestMarketContextHelpers:
    def test_realized_volatility_empty(self):
        assert realized_volatility([]) == 0.0

    def test_realized_volatility_bounded(self):
        closes = [100.0, 101.0, 99.5, 102.0, 100.5]
        value = realized_volatility(closes)
        assert 0.0 <= value <= 1.0

    def test_spread_bps_from_bar(self):
        assert spread_bps(101.0, 99.0, 100.0) == pytest.approx(200.0)


class TestMarketContextBuilder:
    @pytest.mark.asyncio
    async def test_build_uses_session_preferences(self):
        event_risk_layer = MagicMock()
        event_risk_layer.locked_instrument_ids = AsyncMock(return_value=frozenset())
        event_risk_layer.locked_sleeve_ids = AsyncMock(return_value=frozenset())
        liquidity_monitor = MagicMock()
        liquidity_monitor.locked_instrument_ids = AsyncMock(return_value=frozenset())
        builder = MarketContextBuilder(
            total_capital_usd=100_000,
            event_risk_layer=event_risk_layer,
            liquidity_monitor=liquidity_monitor,
        )
        db = AsyncMock()

        instrument = SimpleNamespace(
            id=101,
            symbol="AAPL",
            category=AssetCategory.EQUITIES.value,
        )
        instrument_result = MagicMock()
        instrument_result.scalar_one_or_none.return_value = instrument

        empty_bars = MagicMock()
        empty_bars.scalars.return_value.all.return_value = []

        empty_news = MagicMock()
        empty_news.scalars.return_value.all.return_value = []

        empty_earnings = MagicMock()
        empty_earnings.scalars.return_value.all.return_value = []

        empty_dividends = MagicMock()
        empty_dividends.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(
            side_effect=[instrument_result, empty_bars, empty_news, empty_earnings, empty_dividends]
        )

        profile = _profile(session_preferences={"session_killed": True})
        sleeve = SimpleNamespace(
            id="sleeve-1",
            status=SleeveStatus.ACTIVE,
            risk_budget=Decimal("5000"),
        )
        context = await builder.build(
            db,
            intent=_intent(),
            profile=profile,
            sleeve=sleeve,
        )

        assert context.session_killed is True
        assert context.instrument_category == AssetCategory.EQUITIES
        assert context.sleeve_risk_budget_remaining == Decimal("5000")


class TestApprovalOrchestrator:
    @pytest.mark.asyncio
    async def test_apply_auto_approve_transitions_intent(self):
        orchestrator = ApprovalOrchestrator()
        db = AsyncMock()

        row = SimpleNamespace(
            id="intent-1",
            status=DealIntentStatus.PENDING_APPROVAL.value,
            exit_logic={},
            updated_at=_NOW,
        )
        intent_result = MagicMock()
        intent_result.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=intent_result)

        decision = PolicyDecision(
            state=PolicyState.AUTO_APPROVE,
            reason="approved",
            risk_score=0.2,
            conditions_met=True,
        )
        await orchestrator.apply_decision(
            db,
            intent_id="intent-1",
            sleeve_id="sleeve-1",
            profile=_profile(),
            decision=decision,
        )

        assert row.status == DealIntentStatus.APPROVED.value
        assert row.exit_logic["last_approval_reason"] == "approved"

    @pytest.mark.asyncio
    async def test_apply_kill_session_flags_profile_and_holds_intents(self):
        orchestrator = ApprovalOrchestrator()
        db = AsyncMock()

        profile_row = SimpleNamespace(
            id="user-1",
            session_preferences={},
            updated_at=_NOW,
        )
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = profile_row

        pending = SimpleNamespace(
            id="intent-pending",
            status=DealIntentStatus.PENDING_APPROVAL.value,
            updated_at=_NOW,
        )
        executing = SimpleNamespace(
            id="intent-exec",
            status=DealIntentStatus.EXECUTING.value,
            updated_at=_NOW,
        )
        intents_result = MagicMock()
        intents_result.scalars.return_value.all.return_value = [pending, executing]

        db.execute = AsyncMock(side_effect=[profile_result, intents_result])

        decision = PolicyDecision(
            state=PolicyState.KILL_SESSION,
            reason="session killed",
            risk_score=0.9,
        )
        await orchestrator.apply_decision(
            db,
            intent_id="intent-pending",
            sleeve_id="sleeve-1",
            profile=_profile(),
            decision=decision,
        )

        assert profile_row.session_preferences["session_killed"] is True
        assert pending.status == DealIntentStatus.HELD.value
        assert executing.status == DealIntentStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_process_and_apply_delegates_to_engine(self):
        engine = AsyncMock(spec=ApprovalPolicyEngine)
        engine.process = AsyncMock(
            return_value=PolicyDecision(
                state=PolicyState.HOLD_FOR_REVIEW,
                reason="manual review",
                risk_score=0.8,
            )
        )
        orchestrator = ApprovalOrchestrator(engine=engine)
        db = AsyncMock()

        row = SimpleNamespace(
            id="intent-1",
            status=DealIntentStatus.PENDING_APPROVAL.value,
            exit_logic={},
            updated_at=_NOW,
        )
        intent_result = MagicMock()
        intent_result.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=intent_result)

        intent = _intent(risk_tag=RiskTag.HIGH, approval_threshold=Decimal("0.4"))
        profile = _profile()
        context = _context()

        decision = await orchestrator.process_and_apply(
            db,
            intent=intent,
            profile=profile,
            context=context,
            user_id="user-1",
        )

        engine.process.assert_awaited_once()
        assert decision.state == PolicyState.HOLD_FOR_REVIEW
        assert row.status == DealIntentStatus.HELD.value
