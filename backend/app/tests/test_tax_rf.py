"""K3 RF tax demo — golden answers from docs/qa/evidence/k3/manual-calc.md."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.services.legal.catalog import load_ui_texts, reset_cache
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.tax_rf.service import demo_tax_payload, fixture_tax_payload, lth_unlock_date
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    reset_cache()


def teardown_function() -> None:
    reset_for_tests()
    clear_session_user()
    reset_cache()


def test_flag_default_off() -> None:
    from app.services.qa.feature_flags import is_enabled

    assert is_enabled("qa_tax_rf") is False


def test_flag_off_by_default() -> None:
    out = demo_tax_payload("u1")
    assert out["status"] == "flag_off"
    assert out["flag"] == "qa_tax_rf"


def test_lth_unlock_date() -> None:
    assert lth_unlock_date(date(2023, 1, 15)) == date(2026, 1, 15)
    assert lth_unlock_date(date(2020, 2, 29)) == date(2023, 2, 28)


def test_demo_ytd_and_harvest_golden() -> None:
    out = fixture_tax_payload("u1")
    assert out["status"] == "demo"
    assert out["ytd"]["tax_base"] == "1000000.00"
    assert out["ytd"]["tax_cash"] == "130000.00"
    # Unrealized GAZP loss −1500 → base 998500 → tax 129805 → saving 195
    assert out["harvest"]["tax_cash_reduction"] == "195.00"
    assert out["harvest"]["after_harvest_tax_cash"] == "129805.00"


def test_demo_lth_sber_eligible() -> None:
    out = fixture_tax_payload("u1")
    sber = next(p for p in out["positions"] if p["ticker"] == "SBER")
    assert sber["lth_unlock_on"] == "2026-01-15"
    assert sber["lth_eligible_today"] is True
    assert sber["unrealized_result"] == "8000.00"
    assert sber["tax_if_sell_today"] == "0.00"
    assert sber["tax_base_if_sell_today"] == "0.00"


def test_demo_iis_type_a_base() -> None:
    out = fixture_tax_payload("u1")
    assert out["iis"]["applied"] is True
    assert out["iis"]["deduction_base"] == "400000.00"
    assert Decimal(str(out["iis"]["tax_cash"])) == Decimal("52000.00")


def test_flag_on_empty_book_is_no_data() -> None:
    set_global("qa_tax_rf", True)
    out = demo_tax_payload("u-empty-tax")
    assert out["status"] == "нет данных"
    assert out["data_status"] == "нет данных"
    assert out["positions"] == []
    assert "GAZP" not in str(out)


def test_http_flag_off_and_texts() -> None:
    bind_session_user("u-k3")
    client = TestClient(app)
    res = client.get("/api/v1/tax/demo")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "flag_off"
    assert body["lawyer_gate"] == "[ЮРИСТ]"
    texts = load_ui_texts()["tax"]
    assert texts["lawyer_unconfirmed"] == "методика не подтверждена юристом"
    blob = " ".join(str(v).lower() for v in texts.values())
    assert "не налоговая консультация" in blob
    assert "советуем" not in blob
    assert "купите" not in blob
    assert "продайте" not in blob
    assert texts["no_data"] == "нет данных"
