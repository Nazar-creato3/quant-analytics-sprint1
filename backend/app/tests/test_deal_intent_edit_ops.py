"""Unit tests for DealIntent edit operations (Prompt 96)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.deal_intent import DealIntentRead
from app.domain.deal_intent_enums import DealIntentStatus
from app.schemas.schemas import DealIntentEditRequest
from app.services.approval.deal_intent_ops import DealIntentOperationError, edit_deal_intent

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_edit_request_accepts_full_pre_approval_payload():
    body = DealIntentEditRequest.model_validate(
        {
            "target_price": 101.2,
            "direction": "short",
            "required_confidence": 0.81,
            "max_slippage_bps": 25,
            "max_spread_bps": 12,
            "time_in_force": "gtc",
            "trigger_type": "market",
            "approval_threshold": 0.7,
            "risk_tag": "event_risk",
            "hedge_attachment_id": "660e8400-e29b-41d4-a716-446655440001",
            "exit_logic": {
                "stop_loss": {"price": 98.0},
                "take_profit": {"price": 108.0},
                "trailing": {"pct": 1.5},
                "partial_close": {"pct": 40},
                "time_exit": {"hours": 72},
            },
        }
    )
    assert body.direction == "short"
    assert body.max_slippage_bps == 25
    assert body.exit_logic["trailing"] == {"pct": 1.5}


def _intent_row(**overrides):
    base = dict(
        id="intent-96",
        instrument_id=1,
        sleeve_id="sleeve-1",
        direction="long",
        target_price=Decimal("100"),
        entry_reason="test entry",
        strategy="trend",
        required_confidence=0.72,
        max_slippage_bps=15,
        max_spread_bps=8,
        time_in_force="day",
        trigger_type="limit",
        exit_logic={"stop_loss": {"price": 95.0}, "take_profit": {"price": 110.0}},
        hedge_attachment_id=None,
        approval_threshold=Decimal("0.65"),
        risk_tag="medium",
        news_lock=False,
        correlation_lock=False,
        volatility_lock=False,
        status=DealIntentStatus.PENDING_APPROVAL.value,
        created_at=_NOW,
        updated_at=_NOW,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_edit_pre_approval_persists_scalar_fields():
    row = _intent_row()
    db = AsyncMock()
    intent_result = MagicMock()
    intent_result.scalar_one_or_none.return_value = row
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[intent_result, user_result])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    result = await edit_deal_intent(
        db,
        "intent-96",
        "op@test.com",
        target_price=Decimal("101.5"),
        direction="short",
        max_slippage_bps=20,
        trigger_type="market",
        risk_tag="high",
    )

    assert isinstance(result, DealIntentRead)
    assert row.target_price == Decimal("101.5")
    assert row.direction == "short"
    assert row.max_slippage_bps == 20
    assert row.trigger_type == "market"
    assert row.risk_tag == "high"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_open_position_allows_exit_logic_only():
    row = _intent_row(status=DealIntentStatus.FILLED.value)
    db = AsyncMock()
    intent_result = MagicMock()
    intent_result.scalar_one_or_none.return_value = row
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[intent_result, user_result])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await edit_deal_intent(
        db,
        "intent-96",
        None,
        exit_logic={"trailing": {"pct": 3.0}, "partial_close": {"pct": 25}},
    )

    assert row.exit_logic["trailing"] == {"pct": 3.0}
    assert row.exit_logic["partial_close"] == {"pct": 25}
    assert row.exit_logic["stop_loss"] == {"price": 95.0}


@pytest.mark.asyncio
async def test_edit_open_position_rejects_target_price():
    row = _intent_row(status=DealIntentStatus.EXECUTING.value)
    db = AsyncMock()
    intent_result = MagicMock()
    intent_result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=intent_result)

    with pytest.raises(DealIntentOperationError, match="exit controls only"):
        await edit_deal_intent(db, "intent-96", None, target_price=Decimal("99"))


@pytest.mark.asyncio
async def test_edit_open_position_rejects_disallowed_exit_keys():
    row = _intent_row(status=DealIntentStatus.APPROVED.value)
    db = AsyncMock()
    intent_result = MagicMock()
    intent_result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=intent_result)

    with pytest.raises(DealIntentOperationError, match="cannot edit exit_logic keys"):
        await edit_deal_intent(
            db,
            "intent-96",
            None,
            exit_logic={"position_size_usd": 9000},
        )
