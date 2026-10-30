"""Unit and property-based tests for ApprovalPolicyEngine."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.deal_intent import DealIntentRead
from app.domain.deal_intent_enums import (
    DealIntentDirection,
    DealIntentStatus,
    RiskTag,
    TimeInForce,
    TriggerType,
)
from app.domain.enums import AssetCategory, SleeveStatus, Strategy
from app.domain.profile import (
    AutomationLevel,
    ExecutionStyle,
    ProfileMode,
    ProfileRead,
    RiskAppetite,
    TimeHorizon,
)
from app.services.approval.engine import AUTO_APPROVE_MAX_RISK, compute_risk_score, evaluate_policy
from app.services.approval.models import MarketContext, PolicyState
from app.services.approval.service import ApprovalPolicyEngine

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _profile(**overrides: object) -> ProfileRead:
    defaults = {
        "id": "user-1",
        "risk_appetite": RiskAppetite.MODERATE,
        "max_drawdown_pct": Decimal("15"),
        "max_daily_loss_abs": Decimal("5000"),
        "allowed_categories": [AssetCategory.EQUITIES, AssetCategory.ETF],
        "allowed_instrument_ids": [],
        "approval_policy_id": None,
        "time_horizon": TimeHorizon.SWING,
        "execution_style": ExecutionStyle.ACTIVE,
        "volatility_tolerance": 0.6,
        "hedge_preference": False,
        "leverage_max": Decimal("1"),
        "mode": ProfileMode.PAPER,
        "automation_level": AutomationLevel.SEMI_AUTO,
        "session_preferences": {},
        "news_sensitivity": 0.5,
        "event_sensitivity": 0.5,
        "diversification_policy": {"max_correlation": 0.7},
        "paper_trading_days": 45,
        "paper_sharpe": 1.0,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return ProfileRead(**defaults)


def _intent(**overrides: object) -> DealIntentRead:
    defaults = {
        "id": "intent-1",
        "instrument_id": 101,
        "sleeve_id": "sleeve-1",
        "direction": DealIntentDirection.LONG,
        "entry_reason": "momentum breakout",
        "strategy": Strategy.TREND,
        "required_confidence": 0.8,
        "max_slippage_bps": 50,
        "max_spread_bps": 25,
        "time_in_force": TimeInForce.GTC,
        "trigger_type": TriggerType.MARKET,
        "approval_threshold": Decimal("0.75"),
        "risk_tag": RiskTag.LOW,
        "status": DealIntentStatus.PENDING_APPROVAL,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return DealIntentRead(**defaults)


def _context(**overrides: object) -> MarketContext:
    defaults = {
        "instrument_volatility": 0.2,
        "instrument_spread_bps": 5.0,
        "instrument_category": AssetCategory.EQUITIES,
        "max_correlation_with_portfolio": 0.3,
        "news_locked_instrument_ids": frozenset(),
        "market_regime": "trend",
        "session_killed": False,
        "profile_drawdown_pct": 2.0,
        "profile_daily_loss_abs": Decimal("100"),
        "sleeve_status": SleeveStatus.ACTIVE,
        "sleeve_risk_budget_remaining": Decimal("10000"),
        "freeze_sleeve_requested": False,
    }
    defaults.update(overrides)
    return MarketContext(**defaults)


class TestPolicyDecisionInvariants:
    @given(
        risk_tag=st.sampled_from(list(RiskTag)),
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        news_lock=st.booleans(),
        corr_lock=st.booleans(),
        vol_lock=st.booleans(),
    )
    @settings(max_examples=200, deadline=None)
    def test_risk_score_bounded(
        self,
        risk_tag: RiskTag,
        confidence: float,
        news_lock: bool,
        corr_lock: bool,
        vol_lock: bool,
    ) -> None:
        intent = _intent(
            risk_tag=risk_tag,
            required_confidence=confidence,
            news_lock=news_lock,
            correlation_lock=corr_lock,
            volatility_lock=vol_lock,
        )
        score = compute_risk_score(intent)
        assert 0.0 <= score <= 1.0

    @given(
        session_killed=st.booleans(),
        sleeve_frozen=st.booleans(),
        drawdown=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
        daily_loss=st.decimals(min_value=0, max_value=100000, allow_nan=False),
    )
    @settings(max_examples=150, deadline=None)
    def test_decision_reason_non_empty(
        self,
        session_killed: bool,
        sleeve_frozen: bool,
        drawdown: float,
        daily_loss: Decimal,
    ) -> None:
        profile = _profile(max_drawdown_pct=Decimal("10"), max_daily_loss_abs=Decimal("1000"))
        intent = _intent(risk_tag=RiskTag.MEDIUM, approval_threshold=Decimal("0.95"))
        context = _context(
            session_killed=session_killed,
            sleeve_status=SleeveStatus.FROZEN if sleeve_frozen else SleeveStatus.ACTIVE,
            profile_drawdown_pct=drawdown,
            profile_daily_loss_abs=daily_loss,
        )
        decision = evaluate_policy(intent, profile, context)
        assert decision.reason.strip()
        assert 0.0 <= decision.risk_score <= 1.0


class TestPolicyPriority:
    def test_kill_session_overrides_auto_approve(self):
        decision = evaluate_policy(
            _intent(risk_tag=RiskTag.LOW),
            _profile(),
            _context(session_killed=True),
        )
        assert decision.state == PolicyState.KILL_SESSION

    def test_kill_session_on_drawdown_breach(self):
        decision = evaluate_policy(
            _intent(),
            _profile(max_drawdown_pct=Decimal("10")),
            _context(profile_drawdown_pct=12.0),
        )
        assert decision.state == PolicyState.KILL_SESSION

    def test_freeze_sleeve_when_budget_exhausted(self):
        decision = evaluate_policy(
            _intent(),
            _profile(),
            _context(sleeve_risk_budget_remaining=Decimal("0")),
        )
        assert decision.state == PolicyState.FREEZE_SLEEVE

    def test_reject_hard_for_disallowed_category(self):
        decision = evaluate_policy(
            _intent(),
            _profile(allowed_categories=[AssetCategory.ETF]),
            _context(instrument_category=AssetCategory.CRYPTO),
        )
        assert decision.state == PolicyState.REJECT_HARD

    def test_reject_hard_correlation_lock_breach(self):
        decision = evaluate_policy(
            _intent(correlation_lock=True),
            _profile(diversification_policy={"max_correlation": 0.5}),
            _context(max_correlation_with_portfolio=0.9),
        )
        assert decision.state == PolicyState.REJECT_HARD


class TestApprovalPaths:
    def test_auto_approve_low_risk_clean_context(self):
        decision = evaluate_policy(_intent(risk_tag=RiskTag.LOW), _profile(), _context())
        assert decision.state == PolicyState.AUTO_APPROVE
        assert decision.is_approvable
        assert decision.conditions_met is True

    def test_hold_for_review_high_risk_score(self):
        decision = evaluate_policy(
            _intent(risk_tag=RiskTag.HIGH, approval_threshold=Decimal("0.5")),
            _profile(),
            _context(),
        )
        assert decision.state == PolicyState.HOLD_FOR_REVIEW

    def test_hold_for_review_event_risk_tag(self):
        decision = evaluate_policy(
            _intent(risk_tag=RiskTag.EVENT_RISK, approval_threshold=Decimal("0.99")),
            _profile(),
            _context(),
        )
        assert decision.state == PolicyState.HOLD_FOR_REVIEW

    def test_conditional_approve_medium_risk(self):
        decision = evaluate_policy(
            _intent(
                risk_tag=RiskTag.MEDIUM,
                required_confidence=0.85,
                approval_threshold=Decimal("0.95"),
            ),
            _profile(),
            _context(),
        )
        assert decision.state == PolicyState.CONDITIONAL_APPROVE
        assert decision.conditions_met is True

    def test_hold_when_news_lock_blocks_conditional(self):
        decision = evaluate_policy(
            _intent(
                risk_tag=RiskTag.MEDIUM,
                required_confidence=0.85,
                approval_threshold=Decimal("0.95"),
                news_lock=True,
            ),
            _profile(),
            _context(),
        )
        assert decision.state == PolicyState.HOLD_FOR_REVIEW
        assert decision.conditions_met is False

    def test_hold_when_spread_too_wide(self):
        decision = evaluate_policy(
            _intent(
                risk_tag=RiskTag.MEDIUM,
                required_confidence=0.85,
                approval_threshold=Decimal("0.95"),
                max_spread_bps=5,
            ),
            _profile(),
            _context(instrument_spread_bps=20.0),
        )
        assert decision.state == PolicyState.HOLD_FOR_REVIEW


class TestPropertyCombinations:
    @given(
        volatility=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        tolerance=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        spread_bps=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
        max_spread=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=200, deadline=None)
    def test_conditional_fails_when_volatility_or_spread_exceed_limits(
        self,
        volatility: float,
        tolerance: float,
        spread_bps: float,
        max_spread: int,
    ) -> None:
        profile = _profile(volatility_tolerance=tolerance)
        intent = _intent(
            risk_tag=RiskTag.MEDIUM,
            required_confidence=0.85,
            approval_threshold=Decimal("0.95"),
            max_spread_bps=max_spread,
        )
        context = _context(instrument_volatility=volatility, instrument_spread_bps=spread_bps)
        decision = evaluate_policy(intent, profile, context)

        vol_fail = volatility > tolerance
        spread_fail = spread_bps > max_spread
        if vol_fail or spread_fail:
            assert decision.state in {
                PolicyState.HOLD_FOR_REVIEW,
                PolicyState.REJECT_HARD,
                PolicyState.FREEZE_SLEEVE,
                PolicyState.KILL_SESSION,
            }

    @given(
        approval_threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        risk_tag=st.sampled_from([RiskTag.HIGH, RiskTag.EVENT_RISK]),
    )
    @settings(max_examples=80, deadline=None)
    def test_high_risk_tags_trigger_review_or_reject(
        self,
        approval_threshold: float,
        risk_tag: RiskTag,
    ) -> None:
        intent = _intent(risk_tag=risk_tag, approval_threshold=Decimal(str(approval_threshold)))
        decision = evaluate_policy(intent, _profile(), _context())
        assert decision.state in {
            PolicyState.HOLD_FOR_REVIEW,
            PolicyState.REJECT_HARD,
            PolicyState.KILL_SESSION,
            PolicyState.FREEZE_SLEEVE,
        }


class TestApprovalPolicyService:
    @pytest.mark.asyncio
    async def test_process_writes_audit_and_review_queue(self):
        engine = ApprovalPolicyEngine()
        db = AsyncMock()
        intent = _intent(risk_tag=RiskTag.HIGH, approval_threshold=Decimal("0.4"))
        profile = _profile()
        context = _context()

        decision = await engine.process(
            db,
            intent=intent,
            profile=profile,
            context=context,
            user_id="user-1",
        )

        assert decision.state == PolicyState.HOLD_FOR_REVIEW
        assert db.add.call_count == 2
        audit_row = db.add.call_args_list[0].args[0]
        review_row = db.add.call_args_list[1].args[0]
        assert audit_row.action == "approval_policy.hold_for_review"
        assert audit_row.details["reason"] == decision.reason
        assert review_row.deal_intent_id == intent.id
        assert review_row.reason == decision.reason

    @pytest.mark.asyncio
    async def test_process_reject_hard_audit_marks_failure(self):
        engine = ApprovalPolicyEngine()
        db = AsyncMock()
        intent = _intent()
        profile = _profile(allowed_categories=[AssetCategory.ETF])
        decision = await engine.process(
            db,
            intent=intent,
            profile=profile,
            context=_context(instrument_category=AssetCategory.CRYPTO),
        )
        assert decision.state == PolicyState.REJECT_HARD
        audit_row = db.add.call_args_list[0].args[0]
        assert audit_row.success is False
        assert audit_row.error == decision.reason


class TestDealIntentIntegration:
    def test_auto_approve_band_constant(self):
        intent = _intent(risk_tag=RiskTag.LOW, required_confidence=0.95)
        assert compute_risk_score(intent) <= AUTO_APPROVE_MAX_RISK
