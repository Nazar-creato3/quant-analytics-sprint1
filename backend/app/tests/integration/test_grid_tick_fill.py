"""Integration tests for grid bot price-cross fill simulation."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.grid.tick import apply_price_tick


def _sample_bot(*, last_price: float, levels: list[dict]) -> dict:
    return {
        "config": {
            "ticker": "AAPL",
            "lower_price": 170.0,
            "upper_price": 200.0,
            "grid_count": 10,
            "total_capital": 10000.0,
            "entry_price": last_price,
        },
        "summary": {"last_price": last_price, "ticker": "AAPL"},
        "levels": levels,
        "realized_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
    }


class TestGridPriceCrossFill:
    def test_buy_fill_when_price_crosses_down_through_level(self):
        bot = _sample_bot(
            last_price=185.0,
            levels=[
                {
                    "price": 180.0,
                    "side": "buy",
                    "quantity": 10.0,
                    "status": "pending",
                    "fill_price": None,
                    "pnl": 0.0,
                },
            ],
        )

        updated = apply_price_tick(bot, 179.0)

        assert updated["total_trades"] == 1
        filled = [level for level in updated["levels"] if level["status"] == "filled"]
        assert len(filled) == 1
        assert filled[0]["side"] == "buy"
        assert updated["summary"]["last_price"] == 179.0

    def test_sell_fill_when_price_crosses_up_through_level(self):
        bot = _sample_bot(
            last_price=185.0,
            levels=[
                {
                    "price": 190.0,
                    "side": "sell",
                    "quantity": 10.0,
                    "status": "pending",
                    "fill_price": None,
                    "pnl": 0.0,
                },
            ],
        )

        updated = apply_price_tick(bot, 191.0)

        assert updated["total_trades"] == 1
        filled = [level for level in updated["levels"] if level["status"] == "filled"]
        assert len(filled) == 1
        assert filled[0]["side"] == "sell"

    def test_no_fill_without_price_cross(self):
        bot = _sample_bot(
            last_price=185.0,
            levels=[
                {
                    "price": 180.0,
                    "side": "buy",
                    "quantity": 10.0,
                    "status": "pending",
                    "fill_price": None,
                    "pnl": 0.0,
                },
            ],
        )

        updated = apply_price_tick(bot, 185.0)

        assert updated["total_trades"] == 0
        assert all(level["status"] == "pending" for level in updated["levels"])


@pytest.mark.asyncio
async def test_grid_tick_task_uses_yfinance_for_equities():
    from app.tasks.grid import _async_tick_grid_bots

    bot_id = "bot-aapl"
    bots = {
        bot_id: _sample_bot(
            last_price=185.0,
            levels=[
                {
                    "price": 180.0,
                    "side": "buy",
                    "quantity": 10.0,
                    "status": "pending",
                    "fill_price": None,
                    "pnl": 0.0,
                },
            ],
        )
    }

    with (
        patch("app.api.v1.endpoints.grid._load_all_bots", new_callable=AsyncMock, return_value=bots),
        patch("app.api.v1.endpoints.grid._save_all_bots", new_callable=AsyncMock) as save_mock,
        patch(
            "app.services.market_data.client.get_grid_tick_quote",
            new_callable=AsyncMock,
            return_value={"ticker": "AAPL", "price": 179.0, "source": "yfinance"},
        ) as quote_mock,
    ):
        result = await _async_tick_grid_bots()

    quote_mock.assert_awaited_once_with("AAPL")
    save_mock.assert_awaited_once()
    assert result["updated"] == 1
    assert result["fills"] == 1
    assert bots[bot_id]["total_trades"] == 1
