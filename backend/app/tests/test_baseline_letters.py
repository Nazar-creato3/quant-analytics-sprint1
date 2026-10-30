"""Baseline letters в, д, е, ж, з on the in-process API. Letter б is Lane 1."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.act_desk.service import (
    hypothetical_holdings,
    preview_orders,
    preview_trade,
    reset as reset_act,
    save_profile,
)
from app.services.concentration.service import analyze_portfolio
from app.services.order_machine.service import reset as reset_orders, submit_order
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.portfolio_report.service import assemble
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.returns.service import as_dict as returns_as_dict
from app.services.returns.service import compute_returns
from app.services.risk_engine.series import put_series, reset as reset_series
from app.services.risk_engine.service import compute_risk_for_holdings, compute_risk_for_user, invalidate
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    reset_act()
    reset_orders()
    get_book().reset()
    reset_series()
    invalidate()
    set_global("qa_venue_adapters", True)
    set_global("qa_act_desk", True)
    set_global("qa_order_machine", True)
    set_global("qa_risk_engine", True)
    set_global("qa_report", True)


def teardown_function() -> None:
    reset_orders()
    reset_act()
    get_book().reset()
    reset_series()
    invalidate()
    reset_for_tests()
    clear_session_user()


def _seed(user_id: str) -> None:
    ensure_account(account_id=f"p-{user_id}", user_id=user_id, venue="act", mode="paper")
    record_transaction(
        account_id=f"p-{user_id}",
        user_id=user_id,
        mode="paper",
        venue="act",
        external_id="sber",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="10",
        amount="1000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )


def test_letter_v_report_matches_returns_risk_concentration() -> None:
    _seed("lane1-v")
    report = assemble(user_id="lane1-v", mode="paper")
    risk = compute_risk_for_user("lane1-v", "paper")
    conc = analyze_portfolio(user_id="lane1-v", mode="paper")
    ret = returns_as_dict(compute_returns(user_id="lane1-v", mode="paper"))
    assert report["risk"]["var_95"] == risk["var_95"]
    assert report["risk"]["es_975"] == risk["es_975"]
    assert report["concentration"]["hhi"] == conc["hhi"]
    assert report["first_screen"]["var_95"] == risk["var_95"]
    assert report["first_screen"]["hhi"] == conc["hhi"]
    assert report["first_screen"]["twr"] == ret.get("twr")
    assert report["first_screen"]["mwr"] == ret.get("mwr")
    bind_session_user("lane1-v")
    client = TestClient(app)
    body = client.get("/api/v1/report", params={"user_id": "lane1-v", "mode": "paper"}).json()
    assert body["first_screen"]["var_95"] == risk["var_95"]
    assert body["first_screen"]["twr"] == ret.get("twr")
    assert body["first_screen"]["mwr"] == ret.get("mwr")
    assert body["first_screen"]["hhi"] == conc["hhi"]


def test_letter_d_preview_after_differs_and_matches_risk_service() -> None:
    save_profile(
        "lane1-d",
        {
            "horizon": "3y",
            "risk_tolerance": "moderate",
            "max_position_pct": "0.90",
            "max_crisis_loss_pct": "0.30",
            "expected_return": "0.08",
        },
    )
    _seed("lane1-d")
    market = [0.01 if i % 2 == 0 else -0.02 for i in range(60)]
    put_series("SBER", market)
    put_series("GAZP", [-x for x in market])
    put_series("IMOEX", market)
    orders = [{"ticker": "GAZP", "side": "buy", "qty": "10", "price": "100"}]
    preview = preview_trade(user_id="lane1-d", ticker="GAZP", qty="10", price="100")
    assert preview["delta"]["var_95"]["before"] != preview["delta"]["var_95"]["after"]
    holdings = hypothetical_holdings("lane1-d", "paper", orders)
    risk = compute_risk_for_holdings(holdings)
    assert preview["delta"]["var_95"]["after"] == risk["var_95"]
    assert preview["delta"]["es_975"]["after"] == risk["es_975"]


def test_letter_e_no_price_does_not_compute_qty() -> None:
    import pytest

    with pytest.raises(ValueError, match="нет данных"):
        preview_orders(user_id="lane1-e", orders=[{"ticker": "SBER", "qty": "10", "price": ""}])


def test_letter_zh_order_refuses_on_gate_error() -> None:
    row = submit_order(
        user_id="lane1-zh",
        client_order_id="lane1-zh-1",
        ticker="",
        side="buy",
        qty="1",
        ccy="RUB",
        price="100",
        mode="paper",
        confirmed=True,
    )
    assert row["status"] == "rejected"


def test_letter_z_quote_envelope_without_price_has_no_number() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/market/quote-envelope", params={"symbol": "SBER"})
    assert res.status_code == 200, res.text
    body = res.json()
    price = body.get("price")
    assert price in (None, "", "нет данных")
    assert body.get("freshness_label") == "нет данных"
