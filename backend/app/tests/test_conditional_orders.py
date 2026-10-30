"""Tests for conditional order manager and celery polling task."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.orders.conditional_manager import poll_conditional_orders


@pytest.mark.asyncio
async def test_stop_order_triggers_entry_buy():
    watch = MagicMock()
    watch.id = "w1"
    watch.manual_order_id = "o1"
    watch.ticker = "AAPL"
    watch.trigger_type = "stop"
    watch.trigger_price = 150.0
    watch.trail_distance_pct = None
    watch.peak_price = None
    watch.status = "watching"

    parent = MagicMock()
    parent.id = "o1"
    parent.user_id = "u1"
    parent.ticker = "AAPL"
    parent.side = "buy"
    parent.quantity = 10.0
    parent.order_type = "stop"
    parent.limit_price = None
    parent.stop_price = 150.0
    parent.bracket_stop_loss = None
    parent.bracket_take_profit = None
    parent.maneuver_id = None
    parent.status = "watching"

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[watch])))),
            MagicMock(scalar_one_or_none=MagicMock(return_value=parent)),
        ]
    )
    db.commit = AsyncMock()

    fill = MagicMock(
        status="filled",
        broker_order_id="b1",
        filled_price=151.0,
        filled_qty=10.0,
        filled_at=None,
        submitted_at=None,
    )

    with patch(
        "app.services.market_data.client.get_latest_quote_resolved",
        AsyncMock(return_value={"price": 151.0}),
    ):
        with patch(
            "app.services.trading_keys.user_executor.get_user_executor",
            new=AsyncMock(
                return_value=MagicMock(submit_order=AsyncMock(return_value=fill)),
            ),
        ):
            triggered = await poll_conditional_orders(db)

    assert triggered == 1
    assert parent.status == "filled"
    assert watch.status == "triggered"


def test_celery_beat_includes_conditional_poll():
    from app.tasks.celery_app import celery_app

    assert "poll-conditional-orders-every-30s" in celery_app.conf.beat_schedule
