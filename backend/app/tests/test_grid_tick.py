"""Tests for grid bot paper fill simulation."""
from __future__ import annotations

from app.services.grid.engine import GridBotEngine, GridConfig
from app.services.grid.tick import apply_price_tick
from app.services.market_data.quote_utils import extract_quote_price


def _bot_state(current_price: float) -> dict:
    cfg = GridConfig(
        ticker="AAPL",
        lower_price=170.0,
        upper_price=200.0,
        grid_count=10,
        total_capital=10000.0,
    )
    bot = GridBotEngine(cfg)
    bot.initialize_levels(current_price)
    return {
        "config": {
            "ticker": cfg.ticker,
            "lower_price": cfg.lower_price,
            "upper_price": cfg.upper_price,
            "grid_count": cfg.grid_count,
            "total_capital": cfg.total_capital,
            "take_profit": None,
            "stop_loss": None,
            "entry_price": current_price,
        },
        "summary": bot.get_summary(),
        "levels": [
            {
                "price": l.price,
                "side": l.side,
                "quantity": l.quantity,
                "status": l.status,
                "fill_price": l.fill_price,
                "pnl": l.pnl,
            }
            for l in bot.state.levels
        ],
        "realized_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
    }


class TestGridTickFills:
    def test_buy_fill_when_price_crosses_down(self):
        state = _bot_state(185.0)
        pending_buys = [l for l in state["levels"] if l["side"] == "buy" and l["status"] == "pending"]
        assert pending_buys
        target = max(l["price"] for l in pending_buys)

        updated = apply_price_tick(state, target - 0.01)
        assert updated["total_trades"] >= 1
        assert updated["summary"]["last_price"] == target - 0.01

    def test_extract_quote_price_uses_bid_ask_mid(self):
        assert extract_quote_price({"bid": 100.0, "ask": 102.0}) == 101.0
        assert extract_quote_price({"price": 50.5}) == 50.5

    def test_tick_records_events_and_snapshots(self):
        state = _bot_state(185.0)
        updated = apply_price_tick(state, 184.5)
        assert updated.get("last_activity_at")
        assert len(updated.get("recent_events", [])) >= 1
        assert len(updated.get("pnl_snapshots", [])) >= 1
        assert updated["recent_events"][-1]["type"] == "tick"
