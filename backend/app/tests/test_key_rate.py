"""Prompt 63 key-rate scenarios."""
from __future__ import annotations

from app.services.key_rate.math import bond_price_change_pct, equity_return_from_rate_beta, floater_income, floater_price_change_pct
from app.services.key_rate.service import explain_shift
from app.services.qa.feature_flags import reset_for_tests, set_global


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_key_rate", True)


def teardown_function() -> None:
    reset_for_tests()


def test_ofz_matches_duration_convexity() -> None:
    dy = 0.01
    pct = bond_price_change_pct(mod_duration=5.0, convexity=30.0, dy=dy)
    assert abs(pct - (-5.0 * dy + 0.5 * 30.0 * dy * dy)) < 1e-12


def test_floater_price_near_zero_income_manual() -> None:
    assert floater_price_change_pct() == 0.0
    assert abs(floater_income(notional=1000.0, new_rate=0.15, spread=0.01) - 160.0) < 1e-9


def test_equity_beta_recovers() -> None:
    true = -2.0
    dy = 0.01
    assert abs(equity_return_from_rate_beta(beta=true, dy=dy) - true * dy) < 0.05


def test_cash_shift_does_not_invent_16pct_or_leak_source(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.key_rate.service._holdings_from_book",
        lambda *_a, **_k: [{"ticker": "CASH", "qty": 10000, "price": 1}],
    )
    monkeypatch.setattr("app.services.key_rate.service._nav_rub", lambda *_a, **_k: 10000.0)
    monkeypatch.setattr("app.services.key_rate.service.current_key_rate", lambda *_a, **_k: None)
    out = explain_shift("u1", shift_bp=100)
    assert "meetings_source" not in out
    assert out.get("income_12m") is None
    invented = 10000.0 * (0.16 + 0.01)
    assert out.get("income_12m") != invented
    assert "16" not in (out.get("sentence") or "")


def test_empty_book_no_data() -> None:
    from app.services.portfolio_book.store import get_book

    get_book().reset()
    out = explain_shift("nobody", shift_bp=100)
    assert out["data_status"] == "нет данных"


def test_cash_income_uses_checked_key_rate(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.key_rate.service._holdings_from_book",
        lambda *_a, **_k: [{"ticker": "CASH", "qty": 10000, "price": 1}],
    )
    monkeypatch.setattr("app.services.key_rate.service.current_key_rate", lambda *_a, **_k: 0.14)
    out = explain_shift("u1", shift_bp=100)
    assert abs(out["income_12m"] - 10000.0 * 0.15) < 1e-6


def test_rate_beta_from_decision_days(monkeypatch) -> None:
    from datetime import date

    from app.services.key_rate import service as kr

    eps = [{"date": "2023-07-21", "shift_bp": 100}, {"date": "2023-09-15", "shift_bp": 100},
           {"date": "2025-06-06", "shift_bp": -100}, {"date": "2025-07-25", "shift_bp": -200},
           {"date": "2022-02-28", "shift_bp": 1050}]
    monkeypatch.setattr(kr, "_parse_meetings", lambda: {"episodes": eps})
    # stock falls 2% per +100 bp; the 2022 shock day (−30%) must be ignored
    rets = {date(2023, 7, 21): -0.02, date(2023, 9, 15): -0.02, date(2025, 6, 6): 0.02,
            date(2025, 7, 25): 0.04, date(2022, 2, 28): -0.30}
    monkeypatch.setattr("app.services.price_history.service.dated_returns", lambda _t: rets)
    beta, n = kr.rate_beta("SBER")
    assert n == 4
    assert abs(beta - (-2.0)) < 1e-9
