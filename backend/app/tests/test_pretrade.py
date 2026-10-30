"""Prompt 10: one pre-trade policy, R2 warn vs block, no order bypass."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.bots.common import record_paper_trade
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.pretrade.journal import history, reset as reset_journal
from app.services.pretrade.policy import evaluate
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()
    reset_journal()


def teardown_function() -> None:
    get_book().reset()
    reset_journal()
    reset_for_tests()


def test_human_warns_auto_blocks():
    human = evaluate(
        kind="manual_order",
        actor="human",
        user_id="u1",
        ticker="SBER",
        qty=4000,
        price=30,
        nav=10_000,
    )
    assert human.verdict == "warn"
    assert human.requires_confirm
    assert "купите" not in human.safer.lower()
    confirmed = evaluate(
        kind="manual_order",
        actor="human",
        user_id="u1",
        ticker="SBER",
        qty=4000,
        price=30,
        nav=10_000,
        confirmed=True,
    )
    assert confirmed.verdict == "ok"
    auto = evaluate(
        kind="bot",
        actor="auto",
        user_id="u1",
        ticker="SBER",
        qty=4000,
        price=30,
        nav=10_000,
    )
    assert auto.verdict == "block"
    assert history(user_id="u1")


def test_bot_record_blocked():
    out = record_paper_trade(
        {"user_id": "u2", "symbol": "SBER"},
        bot_id="b1",
        side="buy",
        price=100,
        quantity=5000,
    )
    assert out.get("blocked") is True


def test_orders_service_calls_evaluate():
    app_root = Path(__file__).resolve().parents[1]
    orders = (app_root / "services/orders/service.py").read_text(encoding="utf-8")
    adapter = (app_root / "services/execution/adapter.py").read_text(encoding="utf-8")
    grid = (app_root / "services/grid/execution.py").read_text(encoding="utf-8")
    bots = (app_root / "services/bots/common.py").read_text(encoding="utf-8")
    assert "from app.services.pretrade.policy import assert_allowed, evaluate" in orders
    assert "kind=\"manual_order\"" in orders or 'kind="manual_order"' in orders
    assert "evaluate(" in adapter and "_paper_pretrade" in adapter
    assert "from app.services.pretrade.policy import evaluate" in grid
    assert "except Exception as exc:" in bots
    assert "trades_recorded" in bots


def test_preview_api():
    from app.tests.qa_session import bind_session_user, clear_session_user

    bind_session_user("u3")
    client = TestClient(app)
    res = client.post(
        "/api/v1/risk-gate/preview",
        json={"user_id": "u3", "ticker": "GAZP", "qty": 1, "price": 10, "nav": 10_000},
    )
    assert res.status_code == 200
    assert res.json()["verdict"] == "ok"
    clear_session_user()


def test_evaluate_exception_does_not_record_bot_trade(monkeypatch):
    def boom(**_kwargs):
        raise RuntimeError("gate exploded")

    monkeypatch.setattr("app.services.pretrade.policy.evaluate", boom)
    data: dict = {"user_id": "u-exc", "symbol": "SBER", "paper_trades": []}
    out = record_paper_trade(data, bot_id="b-exc", side="buy", price=100, quantity=1)
    assert out.get("blocked") is True
    assert out.get("trades_recorded") == 0
    assert data.get("paper_trades") == []


def test_no_default_nav_and_flag_off_and_unknown_instrument():
    empty = evaluate(
        kind="bot",
        actor="auto",
        user_id="nobody-nav",
        ticker="SBER",
        qty=1,
        price=10,
    )
    assert empty.verdict == "ok"
    assert all(r.code != "concentration" for r in empty.reasons)
    missing_px = evaluate(
        kind="bot",
        actor="auto",
        user_id="u-px",
        ticker="SBER",
        qty=1,
        price=0,
        nav=10_000,
    )
    assert missing_px.verdict == "block"
    assert any(r.code == "no_price" for r in missing_px.reasons)
    unknown = evaluate(
        kind="bot",
        actor="auto",
        user_id="u-unk",
        ticker="NOTALISTED999",
        qty=1,
        price=10,
        nav=10_000,
    )
    assert unknown.verdict == "block"
    assert any(r.code == "instrument_unavailable" for r in unknown.reasons)
    from app.services.qa.feature_flags import set_global

    set_global("qa_risk_gate", False)
    off = evaluate(
        kind="bot",
        actor="auto",
        user_id="u-off",
        ticker="SBER",
        qty=1,
        price=10,
        nav=10_000,
    )
    assert off.verdict == "block"
    assert any(r.code == "flag_off" for r in off.reasons)


def test_duplicate_asset():
    ensure_account(account_id="p1", user_id="u4", venue="bots", mode="paper")
    record_transaction(
        account_id="p1",
        user_id="u4",
        mode="paper",
        venue="bots",
        external_id="t1",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="10",
        amount="1000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    d = evaluate(
        kind="bot",
        actor="auto",
        user_id="u4",
        ticker="SBER",
        qty=1,
        price=100,
    )
    assert d.verdict == "block"
    assert any(r.code == "duplicate_asset" for r in d.reasons)


def test_empty_position_limit_does_not_skip_weight(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.investment_profile.service.get_profile",
        lambda user_id: {"max_position_pct": "", "banned_tickers": []},
    )
    decision = evaluate(
        kind="manual_order",
        actor="auto",
        user_id="u-empty-limit",
        ticker="SBER",
        qty=10,
        price=100,
        nav=1000,
    )
    assert any(r.code == "profile_weight" for r in decision.reasons)
    assert decision.verdict == "block"
