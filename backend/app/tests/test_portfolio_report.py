"""Prompt 17: report numbers match core services."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.services.concentration.service import analyze_portfolio
from app.services.explanations.service import filter_wording
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.portfolio_report.pdf import render_report_pdf
from app.services.portfolio_report.service import assemble
from app.services.qa.feature_flags import reset_for_tests
from app.tests.qa_session import bind_session_user, clear_session_user
from app.services.risk_engine.service import compute_risk_for_user


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()


def teardown_function() -> None:
    get_book().reset()
    reset_for_tests()
    clear_session_user()


def test_empty_is_not_demo_and_fast():
    out = assemble(user_id="nobody")
    # an empty book is "no data", not a demo portfolio (GA16-303)
    assert out["demo"] is False
    assert out["elapsed_ms"] < 180_000
    assert out["lawyer_flags"]["prefill_order_size"] is False
    assert out["lawyer_flags"]["sandbox"] is False
    assert out["first_screen"]["data_status"] == "нет данных"
    assert out["first_screen"]["equity_vs_benchmark"]["data_status"] == "нет данных"
    assert out["first_screen"]["events_calendar"]["data_status"] == "нет данных"
    assert out["first_screen"]["events_calendar"]["reason"] == "нет данных"
    assert "Промпт" not in str(out["first_screen"]["events_calendar"]["reason"])
    assert filter_wording(out["headline"] + out["disclaimer"]) == []


def test_numbers_match_risk_and_concentration():
    ensure_account(account_id="p1", user_id="u-rep", venue="bots", mode="paper")
    record_transaction(
        account_id="p1",
        user_id="u-rep",
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
    report = assemble(user_id="u-rep", mode="paper")
    risk = compute_risk_for_user("u-rep", "paper")
    conc = analyze_portfolio(user_id="u-rep", mode="paper")
    assert report["risk"]["var_95"] == risk["var_95"]
    assert report["concentration"]["hhi"] == conc["hhi"]
    bind_session_user("u-rep")
    client = TestClient(app)
    body = client.get("/api/v1/report", params={"user_id": "u-rep"}).json()
    assert body["source"] == "portfolio_report"
    assert body["risk"]["var_95"] == risk["var_95"]
    assert body["first_screen"]["var_95"] == risk["var_95"]
    assert body["first_screen"]["hhi"] == conc["hhi"]
    assert body["first_screen"]["data_status"] == "ok"
    pdf = client.get("/api/v1/report/pdf", params={"user_id": "u-rep"})
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    blob = render_report_pdf(body)
    assert blob.startswith(b"%PDF")
    assert b"TWR" in blob or "TWR".encode("latin-1") in blob


def test_e46_03_units_headline_never_prints_fraction_as_rubles():
    from app.services.risk_engine.series import put_series, reset as reset_series

    reset_series()
    put_series("SBER", [0.01] * 40 + [-0.08, -0.06, -0.05])
    ensure_account(account_id="p-units", user_id="u-units", venue="bots", mode="paper")
    record_transaction(
        account_id="p-units",
        user_id="u-units",
        mode="paper",
        venue="bots",
        external_id="t-units",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="10",
        amount="1000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    report = assemble(user_id="u-units", mode="paper")
    frac = report["risk"]["var_95"]
    rub = report["risk"]["rubles_var_95"]
    head = report["headline"]
    assert report["risk"]["var_95_unit"] == "fraction"
    assert report["risk"]["rubles_var_95_unit"] == "RUB"
    assert frac is not None and frac > 0
    assert rub is not None and rub > 0
    assert f"{frac} ₽" not in head
    assert "₽" in head
    conc = report["concentration"]
    assert "Для портфеля 0 ₽" not in str((conc.get("explain") or {}).get("hhi") or {})
    reset_series()


def test_e46_15_equity_vs_benchmark_when_series_exists():
    from app.services.risk_engine.series import put_series, reset as reset_series

    reset_series()
    port = [0.01, 0.02, -0.01]
    bench = [0.0, 0.01, 0.0]
    put_series("SBER", port)
    put_series("MCFTR", bench)
    ensure_account(account_id="p-eq", user_id="u-eq", venue="bots", mode="paper")
    record_transaction(
        account_id="p-eq",
        user_id="u-eq",
        mode="paper",
        venue="bots",
        external_id="t-eq",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="10",
        amount="1000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    report = assemble(user_id="u-eq", mode="paper")
    eq = report["first_screen"]["equity_vs_benchmark"]
    assert eq["data_status"] == "ok"
    assert len(eq["points"]) == 4
    expected = 1.0
    for r in port:
        expected *= 1.0 + r
    assert eq["points"][-1]["portfolio"] == pytest.approx(expected)
    assert eq["benchmark_id"] == "MCFTR"
    reset_series()
