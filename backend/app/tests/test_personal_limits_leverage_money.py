"""GA16-300: leverage uses money notionals, not share counts."""
from __future__ import annotations

from app.services.personal_limits import service as pl
from app.services.qa.feature_flags import reset_for_tests, set_global


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_personal_limits", True)


def teardown_function() -> None:
    reset_for_tests()


def test_expensive_share_counts_as_money(monkeypatch) -> None:
    class P:
        def __init__(self, ticker: str, qty: float) -> None:
            self.ticker = ticker
            self.qty = qty

    monkeypatch.setattr(
        "app.services.portfolio_book.store.get_book",
        lambda: type("B", (), {"positions": staticmethod(lambda **_k: [P("CASH", 100.0), P("SBER", 1.0)])})(),
    )
    monkeypatch.setattr(
        "app.services.concentration.service._trade_price",
        lambda *_a, **_k: 900.0,
    )
    # qty-based would be 1/(100+1)≈0.01; money-based 900/(100+900)=0.9
    hits = pl._leverage_hits("u1", "paper", threshold=0.5)
    assert hits and abs(hits[0]["value"] - 0.9) < 1e-9


def test_missing_price_does_not_invent_leverage(monkeypatch) -> None:
    class P:
        def __init__(self, ticker: str, qty: float) -> None:
            self.ticker = ticker
            self.qty = qty

    monkeypatch.setattr(
        "app.services.portfolio_book.store.get_book",
        lambda: type("B", (), {"positions": staticmethod(lambda **_k: [P("SBER", 10.0)])})(),
    )
    monkeypatch.setattr(
        "app.services.concentration.service._trade_price",
        lambda *_a, **_k: None,
    )
    assert pl._leverage_hits("u1", "paper", threshold=0.01) == []
