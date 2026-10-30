"""E-4-6: empty / missing-price inputs must not invent numbers."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.concentration.service import analyze_portfolio
from app.services.forecast_core.service import forecast
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.calc_result import assert_no_numeric_when_empty
from app.services.qa.feature_flags import reset_for_tests
from app.tests.qa_session import bind_session_user, clear_session_user
from app.services.returns.service import as_dict, compute_returns
from app.services.risk_engine.series import reset as reset_series
from app.services.risk_engine.service import as_dict as risk_dict
from app.services.risk_engine.service import compute_risk, compute_risk_for_user
from app.services.stress_library.service import estimate_exposures, run_holdings, run_portfolio


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()
    reset_series()


def teardown_function() -> None:
    get_book().reset()
    reset_series()
    reset_for_tests()
    clear_session_user()


def test_returns_trade_without_eod_is_no_data():
    ensure_account(account_id="p1", user_id="u", venue="bots", mode="paper")
    record_transaction(
        account_id="p1",
        user_id="u",
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
    out = as_dict(compute_returns(user_id="u", mode="paper"))
    assert out["data_status"] == "нет данных"
    assert out["twr"] is None
    assert out["mwr"] is None
    assert_no_numeric_when_empty(out, ("twr", "mwr"))


def test_risk_empty_and_single_point():
    empty = risk_dict(compute_risk([]))
    assert empty["data_status"] == "нет данных"
    assert empty["var_95"] is None
    assert empty["es_975"] is None
    assert_no_numeric_when_empty(empty, ("var_95", "var_99", "es_975", "volatility", "max_drawdown"))
    one = risk_dict(compute_risk([0.01]))
    assert one["data_status"] == "нет данных"
    assert one["var_95"] is None
    assert_no_numeric_when_empty(one, ("var_95", "es_975"))
    user = compute_risk_for_user("nobody")
    assert user["var_95"] is None
    assert user["data_status"] == "нет данных"
    assert_no_numeric_when_empty(user, ("var_95", "es_975"))


def test_concentration_book_without_trade_price():
    ensure_account(account_id="p1", user_id="c", venue="bots", mode="paper")
    # Position via trade — has price from amount/qty
    record_transaction(
        account_id="p1",
        user_id="c",
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
    ok = analyze_portfolio(user_id="c", mode="paper")
    assert ok.get("data_status") == "ok"
    assert float(ok["weights"]["SBER"]) == 1.0
    empty = analyze_portfolio(user_id="nobody", mode="paper")
    assert empty["data_status"] == "нет данных"
    assert_no_numeric_when_empty(empty, ("hhi",))


def test_stress_empty_and_bond_no_duration():
    empty = run_holdings([])
    assert empty["data_status"] == "нет данных"
    assert empty["nav"] is None
    assert empty["scenarios"] == []
    assert_no_numeric_when_empty(empty, ("nav",))
    exp = estimate_exposures("OFZ26238")
    assert exp["quality"] == "no_history"
    assert exp["betas"].get("duration") is None
    port = run_portfolio(user_id="nobody")
    assert port["data_status"] == "нет данных"
    assert_no_numeric_when_empty(port, ("nav",))


def test_forecast_no_series():
    out = forecast("SBER")
    assert out["data_status"] == "нет данных"
    assert out["probability"] is None
    assert out["interval"] is None
    assert all(not c["available"] for c in out["components"])
    assert_no_numeric_when_empty(out, ("probability",))


def test_api_empty_contracts():
    bind_session_user("nobody-contract")
    client = TestClient(app)
    for path in ("/api/v1/returns", "/api/v1/risk", "/api/v1/report", "/api/v1/stress-library"):
        body = client.get(path, params={"user_id": "nobody-contract"}).json()
        if path.endswith("stress-library"):
            assert body["data_status"] == "нет данных"
            assert body["nav"] is None
        elif path.endswith("returns"):
            assert body["data_status"] == "нет данных"
            assert body["twr"] is None
        elif path.endswith("risk"):
            assert body["data_status"] == "нет данных"
            assert body["var_95"] is None
        else:
            assert body["first_screen"]["data_status"] == "нет данных" or body.get("demo") is True
