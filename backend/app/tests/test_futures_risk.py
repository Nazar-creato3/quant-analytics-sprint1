"""Prompt 58A futures notional, leverage, cushion, hedge."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.futures_risk.math import cushion_to_margin_call, hedge_contracts, notional, portfolio_leverage
from app.services.futures_risk.service import explain
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_futures_risk", True)
    bind_session_user("u58")


def teardown_function() -> None:
    reset_for_tests()
    clear_session_user()


def test_golden_account() -> None:
    mix = notional(qty=1, price=3000, point_value=100)
    cny = notional(qty=2, price=11.5, point_value=1000)
    assert mix == 300_000
    assert cny == 23_000
    lev = portfolio_leverage(notionals=[mix, cny], liquid_nav=1_000_000)
    assert lev is not None and abs(lev - 0.323) < 1e-9
    cush = cushion_to_margin_call(liquid_nav=1_000_000, min_margin=200_000, signed_notional=mix + cny)
    assert cush is not None and abs(cush - 800_000 / 323_000) < 1e-9
    n = hedge_contracts(beta=1.0, portfolio_value=1_000_000, hedge_share=0.5, fut_price=3000, point_value=100)
    assert n is not None and abs(n - 1_000_000 * 0.5 / 300_000) < 1e-9


def test_missing_margin_is_no_cushion() -> None:
    out = explain(
        positions=[{"ticker": "MIX", "qty": 1, "price": 3000, "point_value": 100}],
        liquid_nav=1_000_000,
        min_margin=None,
    )
    assert out["cushion"] is None
    assert out["data_status"] == "частично"
    assert "минимальная маржа" in (out.get("reason") or "")


def test_api() -> None:
    client = TestClient(app)
    res = client.post(
        "/api/v1/futures/risk",
        json={
            "positions": [
                {"ticker": "MIX", "qty": 1, "price": 3000, "point_value": 100, "initial_margin": 40000},
                {"ticker": "CNYRUBF", "qty": 2, "price": 11.5, "point_value": 1000, "perpetual": True},
            ],
            "liquid_nav": 1_000_000,
            "min_margin": 200_000,
            "beta": 1.0,
            "hedge_share": 0.5,
            "hedge_fut_price": 3000,
            "hedge_point_value": 100,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert abs(body["leverage"] - 0.323) < 1e-9
    assert body["hedge"]["contracts"] is not None
