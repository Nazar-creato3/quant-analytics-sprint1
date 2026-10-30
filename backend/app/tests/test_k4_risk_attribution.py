"""K4 Euler vol/CVaR shares, ENB, and what-if (R2, R11)."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.risk_engine.contribution import (
    effective_number_of_bets,
    es_risk_contribution,
    vol_risk_contribution,
)
from app.services.risk_engine.series import put_series, reset as reset_series
from app.services.risk_engine.service import (
    _risk_payload_for_tickers,
    apply_what_if,
    compute_risk_for_holdings,
    compute_what_if,
)
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()
    reset_series()


def teardown_function() -> None:
    get_book().reset()
    reset_series()
    reset_for_tests()
    clear_session_user()


def test_vol_components_sum_to_sigma() -> None:
    cov = [[0.04, 0.01], [0.01, 0.09]]
    out = vol_risk_contribution([0.4, 0.6], cov)
    assert abs(sum(out["component"]) - out["sigma"]) < 1e-9
    assert abs(sum(out["pct"]) - 1.0) < 1e-9


def test_single_name_is_100_percent_of_vol() -> None:
    out = vol_risk_contribution([1.0], [[0.04]])
    assert abs(out["pct"][0] - 1.0) < 1e-9


def test_two_uncorrelated_equal_vol_split_half() -> None:
    cov = [[0.04, 0.0], [0.0, 0.04]]
    out = vol_risk_contribution([0.5, 0.5], cov)
    assert abs(out["pct"][0] - 0.5) < 1e-9
    assert abs(out["pct"][1] - 0.5) < 1e-9


def test_es_components_sum_to_es() -> None:
    rng = np.random.default_rng(7)
    a = rng.normal(0, 0.01, 400)
    b = rng.normal(0, 0.02, 400)
    matrix = np.column_stack([a, b])
    out = es_risk_contribution(matrix.tolist(), [0.5, 0.5])
    assert abs(sum(out["component"]) - out["es"]) < 1e-9


def test_k4_ui_texts_keys() -> None:
    from app.services.legal.catalog import load_ui_texts, reset_cache

    reset_cache()
    k4 = load_ui_texts()["k4"]
    assert k4["title"] == "Откуда риск портфеля"
    assert "CVaR 95%" in k4["pct_cvar"]
    blob = " ".join(str(v).lower() for v in k4.values())
    assert "стоит купить" not in blob
    assert "без риска" not in blob


def test_covariance_estimator_is_sklearn() -> None:
    from app.services.risk_engine.contribution import shrunk_covariance

    rng = np.random.default_rng(1)
    matrix = rng.normal(0, 0.01, size=(80, 2))
    _, estimator = shrunk_covariance(matrix.tolist())
    assert estimator == "sklearn.LedoitWolf"


def test_enb_one_when_one_source() -> None:
    cov = [[0.04, 0.04], [0.04, 0.04]]
    enb = effective_number_of_bets([0.5, 0.5], cov)
    assert enb is not None
    assert enb < 1.2


def test_what_if_remove_does_not_write_book() -> None:
    rng = np.random.default_rng(3)
    put_series("SBER", rng.normal(0, 0.01, 120).tolist())
    put_series("GAZP", rng.normal(0, 0.015, 120).tolist())
    ensure_account(account_id="k4", user_id="k4u", venue="bots", mode="paper")
    for ticker, qty, amount in (("SBER", "2", "200"), ("GAZP", "1", "100")):
        record_transaction(
            account_id="k4",
            user_id="k4u",
            mode="paper",
            venue="bots",
            external_id=f"k4-{ticker}",
            kind="trade",
            instrument_id=ticker,
            ticker=ticker,
            qty=qty,
            amount=amount,
            ccy="RUB",
            event_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
        )
    before = list(get_book().positions(user_id="k4u", mode="paper"))
    payload = compute_what_if(user_id="k4u", remove=["GAZP"])
    after = list(get_book().positions(user_id="k4u", mode="paper"))
    assert payload["persisted"] is False
    tickers = {row["ticker"] for row in payload["attribution"]["components"]}
    assert "GAZP" not in tickers
    assert {p.ticker for p in before} == {p.ticker for p in after}


def test_what_if_api_and_flag() -> None:
    rng = np.random.default_rng(5)
    put_series("SBER", rng.normal(0, 0.01, 80).tolist())
    bind_session_user("k4api")
    client = TestClient(app)
    body = client.post(
        "/api/v1/risk/what-if",
        json={
            "holdings": [{"ticker": "SBER", "qty": "1", "price": "100", "ccy": "RUB"}],
        },
    )
    assert body.status_code == 200
    assert body.json()["persisted"] is False
    assert "elapsed_ms" in body.json()
    set_global("qa_k4_risk_attribution", False)
    off = client.post("/api/v1/risk/what-if", json={"holdings": [{"ticker": "SBER", "qty": "1", "price": "100"}]})
    assert off.status_code == 404


def test_apply_what_if_set_weight_and_cash() -> None:
    base = [
        {"ticker": "SBER", "qty": "1", "price": "80", "ccy": "RUB"},
        {"ticker": "GAZP", "qty": "1", "price": "20", "ccy": "RUB"},
    ]
    rows = apply_what_if(base, set_weight={"SBER": 0.5}, add_cash_rub=100)
    assert any(str(r["ticker"]).upper() == "CASH" for r in rows)


def test_holdings_nav_weights_in_components() -> None:
    rng = np.random.default_rng(9)
    put_series("AAA", rng.normal(0, 0.01, 90).tolist())
    put_series("BBB", rng.normal(0, 0.01, 90).tolist())
    payload = compute_risk_for_holdings(
        [
            {"ticker": "AAA", "qty": "80", "price": "1", "ccy": "RUB"},
            {"ticker": "BBB", "qty": "20", "price": "1", "ccy": "RUB"},
        ]
    )
    by_name = {row["ticker"]: row for row in payload["components"]}
    assert abs(by_name["AAA"]["weight"] - 0.8) < 1e-9
    assert abs(by_name["BBB"]["weight"] - 0.2) < 1e-9


def test_missing_series_hint_has_no_field_name() -> None:
    payload = _risk_payload_for_tickers(["ZZZNONE"], nav_rub=None)
    assert payload["load_report_hint"] == "Нет ряда доходности по позициям."
    assert "total_return" not in payload["load_report_hint"]
    assert "total_return" not in payload["attribution"]["reason"]
