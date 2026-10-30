"""K6 fund report: QuantStats numbers, statement parse, PdN gate, legal keys."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.services.benchmark_alt.prices import put_prices, reset as reset_prices
from app.services.benchmark_alt.service import as_dict, compare_simple_alternatives
from app.services.fund_report.html import render_fund_html
from app.services.fund_report.metrics import fund_metrics
from app.services.fund_report.statement import DEMO_XML, parse_demo, parse_statement, unlink_quietly
from app.services.legal.catalog import load_ui_texts, reset_cache
from app.services.portfolio_book.store import get_book
from app.services.portfolio_report.service import assemble
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.risk_engine.series import put_series, reset as reset_series
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()
    reset_series()
    reset_prices()
    clear_session_user()
    reset_cache()


def teardown_function() -> None:
    get_book().reset()
    reset_series()
    reset_prices()
    reset_for_tests()
    clear_session_user()


def test_fund_metrics_match_independent_drawdown() -> None:
    r = [0.01, -0.02, 0.015, -0.01, 0.005]
    wealth = np.cumprod(1.0 + np.asarray(r))
    peak = np.maximum.accumulate(wealth)
    dd = float((wealth / peak - 1.0).min())
    out = fund_metrics(r)
    assert out["n"] == 5
    assert out["max_dd"] is not None
    assert abs(float(out["max_dd"]) - dd) < 1e-4
    assert out["k1"]["status"] == "pending"
    assert out["k1"]["alternatives"] == []


def test_k6_ui_texts_keys() -> None:
    k6 = load_ui_texts()["k6"]
    assert "пополнениях" in k6["vs_k1"]
    for key in (
        "title",
        "cagr",
        "max_dd",
        "sharpe",
        "monthly",
        "vs_k1",
        "pdf_download",
        "risk",
        "statement_title",
        "statement_demo",
        "file_deleted",
        "mail_wait",
        "basis",
        "method_link",
    ):
        assert k6[key]


def test_parse_demo_xml_and_unlink(tmp_path: Path) -> None:
    parsed = parse_demo()
    assert parsed["ok"] is True
    assert {p["ticker"] for p in parsed["positions"]} >= {"SBER", "GAZP"}
    path = tmp_path / "broker.xml"
    path.write_bytes(DEMO_XML.encode("utf-8"))
    again = parse_statement(path.read_bytes(), filename="broker.xml")
    unlink_quietly(path)
    assert path.exists() is False
    assert again["n"] == parsed["n"]


def test_statement_demo_endpoint_ignores_live_until_pdn() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/report/statement/demo").status_code == 401
    bind_session_user("k6-user")
    demo = client.get("/api/v1/report/statement/demo")
    assert demo.status_code == 200
    body = demo.json()
    assert body["mode"] == "нет данных"
    assert body["parsed"]["positions"] == []
    assert "SBER" not in str(body)
    assert body["live_allowed"] is False
    assert body["file_kept"] is False
    clear_session_user()
    upload = client.post(
        "/api/v1/report/statement",
        files={"file": ("mine.xml", DEMO_XML.encode("utf-8"), "application/xml")},
    )
    assert upload.status_code == 401
    bind_session_user("k6-user")
    authed = client.post(
        "/api/v1/report/statement",
        files={"file": ("mine.xml", DEMO_XML.encode("utf-8"), "application/xml")},
    )
    assert authed.status_code == 200
    assert authed.json()["mode"] == "demo"
    assert authed.json()["reason"] == "pdn_gates"
    pdf = client.get("/api/v1/report/statement/demo.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert b"SBER" not in pdf.content


def test_assemble_fund_uses_risk_series() -> None:
    from datetime import datetime, timezone

    from app.services.portfolio_book.service import ensure_account, record_transaction

    ensure_account(account_id="k6a", user_id="k6-user", venue="bots", mode="paper")
    record_transaction(
        account_id="k6a",
        user_id="k6-user",
        mode="paper",
        venue="bots",
        external_id="k6-sber",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="10",
        amount="2500",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    put_series("SBER", [0.001] * 80)
    report = assemble(user_id="k6-user", mode="paper")
    fund = report["fund"]
    assert fund["n"] == 80
    assert fund["data_status"] == "ok"
    assert fund["max_dd"] is not None
    assert "alternatives" in fund["k1"]
    assert fund["k1"]["status"] in {"ok", "частично", "нет данных", "off"}
    bind_session_user("k6-user")
    client = TestClient(app)
    html = client.get("/api/v1/report/html", params={"user_id": "k6-user"})
    assert html.status_code == 200
    assert "text/html" in html.headers.get("content-type", "")
    assert "Факторы" in html.text
    assert "Ставка" in html.text
    assert "Облигации" in html.text
    assert "Ликвидность" in html.text
    fund_islands = report["fund"]
    for key in ("factors", "stress_rate", "futures", "goals", "bonds", "income", "look_through", "liquidity"):
        assert fund_islands[key].get("reason")


def test_assemble_fund_k1_matches_benchmark_alt() -> None:
    from datetime import date, datetime, timezone

    from app.services.portfolio_book.service import ensure_account, record_transaction

    user = "k6-k1"
    ensure_account(account_id="k6k1", user_id=user, venue="bots", mode="paper")
    record_transaction(
        account_id="k6k1",
        user_id=user,
        mode="paper",
        venue="bots",
        external_id="k6k1-dep",
        kind="deposit",
        instrument_id="CASH",
        ticker="CASH",
        qty="0",
        amount="100000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    put_prices(
        "RGBITR",
        [(date(2024, 1, 2), Decimal("600")), (date(2024, 1, 31), Decimal("606"))],
        source="synthetic_k1_k6",
    )
    put_prices(
        "LQDT",
        [(date(2024, 1, 2), Decimal("100")), (date(2024, 1, 31), Decimal("101"))],
        source="synthetic_k1_k6",
    )
    put_series("SBER", [0.001] * 20)
    expected = as_dict(compare_simple_alternatives(user_id=user, mode="paper", period="inception"))
    report = assemble(user_id=user, mode="paper")
    k1 = report["fund"]["k1"]
    assert k1["status"] in {"ok", "частично"}
    by_ticker = {row["ticker"]: row for row in k1["alternatives"]}
    exp = {row["ticker"]: row for row in expected["alternatives"]}
    assert set(by_ticker) == {"RGBITR", "LQDT"}
    assert by_ticker["RGBITR"]["end_value"] == exp["RGBITR"]["end_value"]
    assert by_ticker["LQDT"]["end_value"] == exp["LQDT"]["end_value"]
    html = render_fund_html(report, texts=load_ui_texts()["k6"])
    assert "RGBITR" in html or "гособлигац" in html.lower()
    set_global("qa_k1_benchmark", False)
    off = assemble(user_id=user, mode="paper")
    assert off["fund"]["k1"]["status"] == "off"
    assert off["fund"]["k1"]["reason"] == "нет данных"
    assert "qa_" not in str(off["fund"]["k1"]["reason"])
