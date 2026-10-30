"""GA16-288: no random equity band; missing floater spread is not zero."""
from __future__ import annotations

from app.services.key_rate.service import explain_shift
from app.services.qa.feature_flags import reset_for_tests, set_global


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_key_rate", True)


def teardown_function() -> None:
    reset_for_tests()


def test_equity_interval_is_not_noise(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.key_rate.service._holdings_from_book",
        lambda *_a, **_k: [{"ticker": "SBER", "qty": 10, "price": 100}],
    )
    monkeypatch.setattr("app.services.key_rate.service._nav_rub", lambda *_a, **_k: 1000.0)
    out = explain_shift(
        "u1",
        shift_bp=100,
        meta={"SBER": {"beta_rates": -2.0, "asset_class": "equity"}},
    )
    assert out["data_status"] == "ok"
    assert out["interval"] is None
    assert out["by_class"]["equity"] != 0.0


def test_missing_floater_spread_not_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.key_rate.service._holdings_from_book",
        lambda *_a, **_k: [{"ticker": "FLOAT1", "qty": 1, "price": 1000}],
    )
    monkeypatch.setattr("app.services.key_rate.service._nav_rub", lambda *_a, **_k: 1000.0)
    out = explain_shift(
        "u1",
        shift_bp=100,
        key_rate=0.16,
        meta={"FLOAT1": {"asset_class": "floater"}},
    )
    assert out["data_status"] == "частично"
    assert "FLOAT1" in (out.get("reason") or "")
    assert out["income_12m"] == 0.0
