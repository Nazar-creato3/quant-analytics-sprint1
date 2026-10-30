"""GA16-282: do not treat holding value as quantity."""
from __future__ import annotations

from app.services.concentration.service import analyze_holdings
from app.services.qa.feature_flags import reset_for_tests, set_global


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_concentration", True)


def test_value_without_qty_is_skipped() -> None:
    out = analyze_holdings(
        [{"ticker": "SBER", "value": "100000", "price": "100", "ccy": "RUB"}]
    )
    assert out.get("empty") is True or out.get("weights") == {}
    assert "SBER" not in (out.get("weights") or {})


def test_explicit_qty_is_kept() -> None:
    out = analyze_holdings(
        [{"ticker": "SBER", "qty": "2", "price": "100", "ccy": "RUB"}]
    )
    assert out["weights"].get("SBER") is not None
    assert any(row.get("qty") == "2" for row in out.get("positions") or [])
