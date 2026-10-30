"""Tests for grid bot paper trade recording and open positions."""
from __future__ import annotations

from app.services.grid.execution import compute_open_positions, record_paper_trade
from app.services.grid.tick import apply_price_tick, build_activity_payload


def _bot_state(*, last_price: float = 185.0) -> dict:
    return {
        "bot_id": "bot-test-1",
        "config": {
            "ticker": "AAPL",
            "lower_price": 170.0,
            "upper_price": 200.0,
            "grid_count": 10,
            "total_capital": 10000.0,
            "entry_price": last_price,
        },
        "summary": {"last_price": last_price, "ticker": "AAPL"},
        "levels": [
            {
                "price": 180.0,
                "side": "buy",
                "quantity": 10.0,
                "status": "pending",
                "fill_price": None,
                "pnl": 0.0,
            },
        ],
        "realized_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
        "paper_trades": [],
    }


class TestGridTickToPositionFlow:
    def test_tick_records_paper_trade_on_fill(self):
        state = _bot_state()
        updated = apply_price_tick(state, 179.0, bot_id="bot-test-1")

        assert updated["total_trades"] == 1
        assert len(updated.get("paper_trades", [])) == 1
        trade = updated["paper_trades"][0]
        assert trade["side"] == "buy"
        assert trade["price"] == 180.0
        assert trade["quantity"] == 10.0

    def test_open_position_after_buy_fill(self):
        state = _bot_state()
        updated = apply_price_tick(state, 179.0, bot_id="bot-test-1")
        updated["levels"][0]["status"] = "filled"
        updated["levels"][0]["fill_price"] = 180.0

        positions = compute_open_positions(updated, 182.0)
        assert len(positions) == 1
        assert positions[0]["ticker"] == "AAPL"
        assert positions[0]["quantity"] == 10.0
        assert positions[0]["unrealized_pnl"] == 20.0

    def test_activity_payload_includes_trades_and_positions(self):
        state = _bot_state()
        updated = apply_price_tick(state, 179.0, bot_id="bot-test-1")
        payload = build_activity_payload("bot-test-1", updated)

        assert payload["bot_id"] == "bot-test-1"
        assert len(payload["paper_trades"]) >= 1
        assert payload["grid_count"] == 10
        assert any(e["type"] == "fill" for e in payload["recent_events"])

    def test_record_paper_trade_appends_to_log(self):
        state = {"paper_trades": [], "config": {"ticker": "AAPL", "total_capital": 10_000.0}}
        record_paper_trade(
            state,
            bot_id="b1",
            side="sell",
            price=190.0,
            quantity=5.0,
            level_price=190.0,
            pnl=12.5,
        )
        assert len(state["paper_trades"]) == 1
        assert state["paper_trades"][0]["pnl"] == 12.5

    def test_ga16_316_missing_ticker_not_unknown(self):
        state = {"paper_trades": [], "config": {"total_capital": 10_000.0}}
        out = record_paper_trade(
            state,
            bot_id="b1",
            side="buy",
            price=100.0,
            quantity=1.0,
            level_price=100.0,
            pnl=0.0,
        )
        assert out.get("blocked") is True
        assert "UNKNOWN" not in str(out)
        assert state["paper_trades"] == []

    def test_ga16_316_pretrade_error_not_str_exc(self, monkeypatch):
        from app.services.pretrade import policy as pretrade_policy

        def _boom(**kwargs):
            raise RuntimeError("secret_stack_trace_xyz")

        monkeypatch.setattr(pretrade_policy, "evaluate", _boom)
        state = {"paper_trades": [], "config": {"ticker": "AAPL", "total_capital": 1_000.0}}
        out = record_paper_trade(
            state,
            bot_id="b1",
            side="buy",
            price=10.0,
            quantity=1.0,
            level_price=10.0,
            pnl=0.0,
        )
        assert out.get("blocked") is True
        assert "secret_stack_trace_xyz" not in str(out)
        assert "RuntimeError" not in str(out)
