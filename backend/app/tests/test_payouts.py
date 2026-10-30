from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.services.legal.catalog import load_ui_texts, reset_cache
from app.services.payouts.calendar_moex import last_buy_date
from app.services.payouts.service import cashflow_summary, notify_copy, portfolio_cashflows, reinvest_scenario, to_ics
from app.services.payouts import store
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_payouts", True)
    store.reset()


def teardown_function() -> None:
    store.reset()
    reset_for_tests()
    clear_session_user()


def test_last_buy_weekend_and_holiday() -> None:
    # 2026-11-09 Monday after 4 Nov holiday and weekend.
    day, src = last_buy_date(date(2026, 11, 9))
    assert day == date(2026, 11, 6)
    assert src == "расчёт"
    day2, src2 = last_buy_date(date(2026, 12, 14), from_broker=date(2026, 12, 11))
    assert day2 == date(2026, 12, 11)
    assert src2 == "данные брокера"


def test_declared_recommended_estimated_and_fund() -> None:
    bind_session_user("u-57")
    book = portfolio_cashflows("u-57", "paper")
    kinds = {(e["instrument"]["ticker"], e["status"]) for e in book["events"]}
    assert ("SBER", "declared") in kinds
    assert ("GAZP", "recommended") in kinds
    assert ("SBER", "estimated") in kinds
    assert ("LQDT", "declared") in kinds
    sber = next(e for e in book["events"] if e["instrument"]["ticker"] == "SBER" and e["status"] == "declared")
    assert sber["last_buy_date"] == "2026-11-06"
    assert abs(sber["amount_gross_rub"] - 2800.0) < 1e-6
    assert abs(sber["tax_rub"] - 364.0) < 1e-6
    assert abs(sber["amount_net_rub"] - 2436.0) < 1e-6
    gazp = next(e for e in book["events"] if e["instrument"]["ticker"] == "GAZP")
    assert gazp["amount_gross_rub"] is None
    est = next(e for e in book["events"] if e["status"] == "estimated")
    assert est["amount_gross_rub"] is None
    assert "ориентир" in est["status_label"]
    foreign = next(e for e in book["events"] if e["instrument"]["ticker"] == "AAPL")
    assert foreign["tax_note"] == "налог может отличаться"
    assert foreign["tax_rub"] is None


def test_summary_and_ics() -> None:
    bind_session_user("u-57")
    summary = cashflow_summary("u-57", "paper", months=12)
    assert summary["passive_declared_net_12m"] is not None
    ics = to_ics(portfolio_cashflows("u-57", "paper")["events"])
    assert ics.startswith("BEGIN:VCALENDAR")
    assert "END:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics
    assert "\r\n" in ics
    assert "Payouts 57" not in ics
    assert "дивиденд" in ics
    book = portfolio_cashflows("u-57", "paper")
    assert book["source"] == "календарь выплат"
    assert "tinvest" not in str(book["source"])


def test_http_and_texts() -> None:
    bind_session_user("u-57")
    client = TestClient(app)
    assert client.get("/api/v1/portfolio/paper/cashflows").status_code == 200
    assert client.get("/api/v1/portfolio/paper/cashflows/summary").status_code == 200
    ics = client.get("/api/v1/portfolio/paper/cashflows.ics")
    assert ics.status_code == 200
    assert "VCALENDAR" in ics.text
    assert client.get("/api/v1/dividends/SBER/gap").status_code == 200
    reset_cache()
    blob = " ".join(str(v).lower() for v in load_ui_texts()["payouts"].values())
    assert "купите" not in blob
    assert "стоит купить" not in blob
    assert "Поступило ожидаемо" in notify_copy(kind="pay", amount=10)


def test_reinvest_reason_has_no_internal_code(monkeypatch) -> None:
    def boom(user_id: str, mode: str = "paper"):
        raise RuntimeError("qa_k1_benchmark off")

    monkeypatch.setattr("app.services.benchmark_alt.service.compare_simple_alternatives", boom)
    out = reinvest_scenario("u-57")
    assert out["reason"] == "нет данных"
    assert "K1" not in out["reason"]

    def ok(user_id: str, mode: str = "paper"):
        return {"data_status": "ok"}

    monkeypatch.setattr("app.services.benchmark_alt.service.compare_simple_alternatives", ok)
    good = reinvest_scenario("u-57")
    assert "K1" not in good["note"]


def test_evidence_12m_matches_hand() -> None:
    bind_session_user("u-57")
    # SBER 80*35=2800 net 2436; LQDT 10*2.5=25 net 21.75; GAZP/estimated no amount.
    summary = cashflow_summary("u-57", "paper", 12)
    assert abs(float(summary["passive_declared_net_12m"]) - 2457.75) < 0.02
