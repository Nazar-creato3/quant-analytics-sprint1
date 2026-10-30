"""K3 tax_ru: golden NDFL / LTH / harvest; demo-only; flag gate."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.tax_ru.math import (
    NO_DATA,
    loss_harvest_rows,
    lth_free_from,
    position_lth_row,
    year_ndfl_estimate,
)
from app.services.tax_ru.rates import coupon_ndfl_rate
from app.services.tax_ru.service import explain_tax
from app.services.target_portfolio.types import TaxLot


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_k3_tax", True)


def teardown_function() -> None:
    reset_for_tests()


def _lot(
    ticker: str,
    *,
    qty: str,
    cost: str,
    acquired: date,
    lot_id: str = "1",
) -> TaxLot:
    return TaxLot(
        lot_id=lot_id,
        ticker=ticker,
        qty=Decimal(qty),
        cost=Decimal(cost),
        acquired=acquired,
    )


def test_lth_free_from_three_years() -> None:
    assert lth_free_from(date(2023, 10, 6)) == date(2026, 10, 6)


def test_year_ndfl_below_and_above_bracket() -> None:
    """Manual: 1_000_000 → 130_000; 3_000_000 → 402_000 (13% to 2.4M + 15%)."""
    sold = date(2026, 6, 1)
    short = date(2026, 1, 1)
    from app.services.target_portfolio.tax import fifo_realize, tax_base_for_year

    lot_b = _lot("AAA", qty="1", cost="100000", acquired=short)
    lot_a = _lot("BBB", qty="1", cost="100000", acquired=short)
    below = tax_base_for_year(
        fifo_realize([lot_b], ticker="AAA", sell_qty=Decimal("1"), sale_price=Decimal("1100000"), sold_on=sold),
        2026,
        resident=True,
    )
    above = tax_base_for_year(
        fifo_realize([lot_a], ticker="BBB", sell_qty=Decimal("1"), sale_price=Decimal("3100000"), sold_on=sold),
        2026,
        resident=True,
    )
    assert Decimal(str(below["tax_cash"])) == Decimal("130000.00")
    assert Decimal(str(above["tax_cash"])) == Decimal("402000.00")
    est = year_ndfl_estimate(
        fifo_realize([lot_b], ticker="AAA", sell_qty=Decimal("1"), sale_price=Decimal("1100000"), sold_on=sold),
        year=2026,
        resident=True,
    )
    assert est["status"] == "ok"
    assert Decimal(str(est["tax_cash"])) == Decimal("130000.00")
    empty = year_ndfl_estimate([], year=2026)
    assert empty["status"] == NO_DATA
    assert empty["tax_cash"] is None


def test_lth_tax_today_vs_after() -> None:
    """Held 3y: sell today may apply relief; after LTH date same mark."""
    acquired = date(2023, 10, 6)
    as_of = date(2026, 10, 6)
    lot = _lot("SBER", qty="10", cost="1000000", acquired=acquired)
    # Mark implies +10M profit on the lot (cost 1M, 10 shares → 1.1M each)
    row = position_lth_row(lot, mark_price=Decimal("1100000"), as_of=as_of, resident=True)
    assert row["status"] == "ok"
    assert row["lth_free_from"] == "2026-10-06"
    assert row["eligible_now"] is True
    assert row["tax_if_sell_today"] is not None
    # After LTH with full years ≥ 3, tax_cash for huge gain with relief is lower than without
    assert Decimal(str(row["tax_if_sell_after_lth"] or "0")) <= Decimal(str(row["tax_if_sell_today"] or "0"))


def test_loss_harvest_reduces_tax() -> None:
    """Realized +500k tax 65k; paper loss -200k → tax 39k; reduction 26k."""
    from app.services.target_portfolio.tax import fifo_realize

    sold = date(2026, 6, 1)
    short = date(2026, 1, 1)
    win = _lot("WIN", qty="1", cost="100000", acquired=short, lot_id="w")
    realized = fifo_realize(
        [win],
        ticker="WIN",
        sell_qty=Decimal("1"),
        sale_price=Decimal("600000"),
        sold_on=sold,
    )
    loser = _lot("LOS", qty="1", cost="300000", acquired=short, lot_id="l")
    rows = loss_harvest_rows(
        [loser],
        marks={"LOS": Decimal("100000")},
        realized_rows=realized,
        as_of=date(2026, 12, 15),
        resident=True,
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert Decimal(str(rows[0]["tax_reduction"])) == Decimal("26000.00")


def test_coupon_rate_uses_k3_when_on() -> None:
    snap = coupon_ndfl_rate()
    assert snap["rate"] == "0.13"
    assert "K3 не готов" not in str(snap.get("note") or "")
    set_global("qa_k3_tax", False)
    off = coupon_ndfl_rate()
    assert off["rate"] == "0.13"
    assert "K3 не готов" in str(off.get("note") or "")


def test_explain_flag_off_and_live_refused() -> None:
    from app.services.portfolio_book.store import get_book

    get_book().reset()
    set_global("qa_k3_tax", False)
    off = explain_tax("u1", mode="paper")
    assert off["data_status"] == NO_DATA
    set_global("qa_k3_tax", True)
    live = explain_tax("u1", mode="live")
    assert live["data_status"] == NO_DATA
    assert "демо" in (live.get("reason") or "").lower() or "paper" in (live.get("reason") or "").lower() or "юрист" in (
        live.get("reason") or ""
    )


def test_explain_empty_book_no_data() -> None:
    from app.services.portfolio_book.store import get_book

    get_book().reset()
    out = explain_tax("nobody-k3", mode="paper")
    assert out["data_status"] == NO_DATA
    assert out["lth"] == []
    assert out["source"] == "данные портфеля"
    assert "portfolio_book" not in str(out["source"])
