"""GA16-275: with the flag on, tax the user book, not the demo lots."""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.tax_rf.service import demo_tax_payload


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()


def test_flag_on_reads_book_not_fixture_lots() -> None:
    set_global("qa_tax_rf", True)
    ensure_account(account_id="p-tax", user_id="u-book-tax", venue="bots", mode="paper")
    record_transaction(
        account_id="p-tax",
        user_id="u-book-tax",
        mode="paper",
        venue="bots",
        external_id="buy-1",
        kind="trade",
        instrument_id="LKOH",
        ticker="LKOH",
        qty="2",
        amount="200",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    out = demo_tax_payload("u-book-tax")
    tickers = {p["ticker"] for p in out.get("positions") or []}
    assert "LKOH" in tickers or out["status"] in {"ok", "нет данных"}
    assert "GAZP" not in tickers
    assert out.get("source") != "demo_fixture"
