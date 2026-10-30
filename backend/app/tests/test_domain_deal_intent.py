"""Unit tests for DealIntent domain entity."""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.deal_intent import DealIntentCreate, DealIntentORM
from app.domain.deal_intent_enums import (
    DealIntentDirection,
    DealIntentStatus,
    RiskTag,
    TimeInForce,
    TriggerType,
)
from app.domain.enums import Strategy


def _sample_intent(**overrides):
    base = dict(
        instrument_id=1,
        sleeve_id="550e8400-e29b-41d4-a716-446655440000",
        direction=DealIntentDirection.LONG,
        target_price=Decimal("150.25"),
        entry_reason="Breakout above resistance with volume confirmation",
        strategy=Strategy.TREND,
        required_confidence=0.72,
        max_slippage_bps=15,
        max_spread_bps=8,
        time_in_force=TimeInForce.DAY,
        trigger_type=TriggerType.LIMIT,
        exit_logic={
            "take_profit": {"price": 160.0},
            "stop_loss": {"price": 145.0},
            "trailing": {"pct": 2.0},
            "time_exit": {"hours": 48},
        },
        approval_threshold=Decimal("0.65"),
        risk_tag=RiskTag.MEDIUM,
    )
    base.update(overrides)
    return DealIntentCreate(**base)


class TestDealIntentCreate:
    def test_create_draft_intent(self):
        intent = _sample_intent()
        assert intent.status == DealIntentStatus.DRAFT
        assert intent.strategy == Strategy.TREND
        assert intent.direction == DealIntentDirection.LONG

    def test_create_short_with_hedge_attachment(self):
        intent = _sample_intent(
            direction=DealIntentDirection.SHORT,
            hedge_attachment_id="660e8400-e29b-41d4-a716-446655440001",
            risk_tag=RiskTag.HIGH,
            trigger_type=TriggerType.MARKET,
        )
        assert intent.hedge_attachment_id == "660e8400-e29b-41d4-a716-446655440001"
        assert intent.risk_tag == RiskTag.HIGH

    def test_lock_flags(self):
        intent = _sample_intent(news_lock=True, correlation_lock=True, volatility_lock=True)
        assert intent.news_lock is True
        assert intent.correlation_lock is True
        assert intent.volatility_lock is True

    @pytest.mark.parametrize(
        "field,value",
        [
            ("required_confidence", 1.1),
            ("required_confidence", -0.01),
            ("max_slippage_bps", -1),
            ("max_spread_bps", -5),
            ("instrument_id", 0),
            ("approval_threshold", Decimal("-0.01")),
        ],
    )
    def test_rejects_invalid_bounds(self, field, value):
        with pytest.raises(ValidationError):
            _sample_intent(**{field: value})

    def test_rejects_blank_entry_reason(self):
        with pytest.raises(ValidationError):
            _sample_intent(entry_reason="   ")

    def test_market_trigger_without_target_price(self):
        intent = _sample_intent(target_price=None, trigger_type=TriggerType.MARKET)
        assert intent.target_price is None
        assert intent.trigger_type == TriggerType.MARKET


class TestDealIntentORM:
    def test_orm_tablename_and_field_assignment(self):
        assert DealIntentORM.__tablename__ == "deal_intents"
        row = DealIntentORM(
            instrument_id=42,
            sleeve_id="sleeve-1",
            direction=DealIntentDirection.LONG.value,
            entry_reason="Mean reversion entry",
            strategy=Strategy.MEAN_REVERSION.value,
            required_confidence=0.55,
            max_slippage_bps=10,
            max_spread_bps=5,
            time_in_force=TimeInForce.GTC.value,
            trigger_type=TriggerType.CONDITION.value,
            exit_logic={"stop_loss": {"price": 90.0}},
            approval_threshold=Decimal("0.5"),
            risk_tag=RiskTag.EVENT_RISK.value,
            status=DealIntentStatus.DRAFT.value,
            news_lock=False,
        )
        assert row.instrument_id == 42
        assert row.strategy == Strategy.MEAN_REVERSION.value

    def test_orm_has_relationships(self):
        assert "instrument" in DealIntentORM.__mapper__.relationships
        assert "sleeve" in DealIntentORM.__mapper__.relationships
        assert "hedge_attachment" in DealIntentORM.__mapper__.relationships
