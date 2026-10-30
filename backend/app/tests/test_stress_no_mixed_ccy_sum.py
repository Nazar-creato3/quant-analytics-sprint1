"""GA16-297: do not sum mixed-currency notionals into RUB without FX."""
from __future__ import annotations

from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.stress_library.service import run_holdings


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_stress_library", True)


def teardown_function() -> None:
    reset_for_tests()


def test_mixed_currencies_are_no_data() -> None:
    out = run_holdings(
        [
            {"ticker": "SBER", "value": 10000, "ccy": "RUB"},
            {"ticker": "AAPL", "value": 500, "ccy": "USD"},
        ]
    )
    assert out["data_status"] == "нет данных"
    assert out["nav"] is None
    assert "валют" in (out.get("reason") or "")
    assert out["scenarios"] == []


def test_single_usd_keeps_usd_not_rub_label() -> None:
    out = run_holdings([{"ticker": "AAPL", "value": 1000, "ccy": "USD"}])
    assert out["data_status"] == "ok"
    assert out["ccy"] == "USD"
    assert out["nav"] == 1000
    assert out["scenarios"]
    assert out["scenarios"][0]["pnl_rub"] is None
    assert out["scenarios"][0]["pnl_money"] is not None
