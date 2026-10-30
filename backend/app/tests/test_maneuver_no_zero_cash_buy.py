"""GA16-301: do not fund a buy from invented zero cash."""
from __future__ import annotations

from decimal import Decimal

from app.services.maneuver_control.service import _apply


def test_buy_without_cash_fails() -> None:
    book = {"SBER": Decimal("10")}
    start = {"SBER": Decimal("100")}
    orders = [{"ticker": "SBER", "side": "buy", "qty": "1", "price": "100"}]
    qty, cash = _apply(book, orders, start)
    assert qty is None
    assert cash == Decimal(0)


def test_buy_with_book_cash_ok() -> None:
    book = {"SBER": Decimal("10"), "CASH": Decimal("500")}
    start = {"SBER": Decimal("100")}
    orders = [{"ticker": "SBER", "side": "buy", "qty": "2", "price": "100"}]
    qty, cash = _apply(book, orders, start)
    assert qty is not None
    assert qty["SBER"] == Decimal("12")
    assert cash == Decimal("300")
