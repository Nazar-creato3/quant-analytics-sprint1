"""GA16-298: trading halt must not report invented zero loss."""
from __future__ import annotations

from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.stress_library.service import run_holdings


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_stress_library", True)


def teardown_function() -> None:
    reset_for_tests()


def test_halt_without_history_is_not_zero_pnl() -> None:
    out = run_holdings([{"ticker": "SBER", "value": 10000, "ccy": "RUB"}])
    halt = next(s for s in out["scenarios"] if s["id"] == "halt_month")
    assert halt["pnl_pct"] is None
    assert halt["pnl_rub"] is None
    assert halt["limited_accuracy"] is True
    assert halt["contributions"][0]["pnl_pct"] is None


def test_halt_with_history_keeps_nonzero_move() -> None:
    hist = {"SBER": [-0.05, -0.02, 0.01]}
    out = run_holdings(
        [{"ticker": "SBER", "value": 10000, "ccy": "RUB"}],
        actual_history=hist,
    )
    halt = next(s for s in out["scenarios"] if s["id"] == "halt_month")
    assert halt["pnl_pct"] is not None
    assert abs(float(halt["pnl_pct"])) > 1e-9
