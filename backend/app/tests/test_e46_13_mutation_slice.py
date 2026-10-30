"""E46-13: CI-light killers for returns/risk/concentration operator mutants (no app.main)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app.services.market_data.eod import EodRow
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests
from app.services.concentration.service import analyze_holdings, holdings_nav
from app.services.returns.service import compute_returns
from app.services.risk_engine.service import compute_risk


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()


def teardown_function() -> None:
    get_book().reset()
    reset_for_tests()


def test_e46_13_empty_var_is_none_not_zero():
    empty = compute_risk([])
    assert empty.var_95 is None
    assert empty.var_99 is None
    assert empty.es_975 is None


def test_e46_13_missing_price_does_not_invent_nav():
    nav, ccy = holdings_nav(
        [
            {"ticker": "SBER", "qty": "10", "price": None, "ccy": "RUB"},
            {"ticker": "GAZP", "qty": "1", "price": "1000", "ccy": "RUB"},
        ]
    )
    assert nav is None
    assert ccy is None
    out = analyze_holdings(
        [
            {"ticker": "SBER", "qty": "10", "price": "100", "ccy": "RUB"},
            {"ticker": "GAZP", "qty": "1", "price": None, "ccy": "RUB"},
        ]
    )
    assert "SBER" in out["weights"]
    assert "GAZP" not in out["weights"]
    assert Decimal(str(out["weights"]["SBER"])) == Decimal("1")


def test_e46_13_trade_pnl_marks_to_official_close_not_cash_amount():
    ensure_account(account_id="p-mtm", user_id="u-mtm", venue="bots", mode="paper")
    record_transaction(
        account_id="p-mtm",
        user_id="u-mtm",
        mode="paper",
        venue="bots",
        external_id="d1",
        kind="deposit",
        instrument_id="CASH",
        ticker="CASH",
        qty="0",
        amount="10000",
        ccy="RUB",
        event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    record_transaction(
        account_id="p-mtm",
        user_id="u-mtm",
        mode="paper",
        venue="bots",
        external_id="t1",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="10",
        amount="1000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    eod = {
        "SBER": EodRow(
            instrument_id="SBER",
            session_date=date(2024, 1, 3),
            official_close=Decimal("150"),
            last_close=Decimal("150"),
            volume=None,
            source="test",
            board=None,
            license_tag="internal_only",
            as_of=date(2024, 1, 3),
        )
    }
    result = compute_returns(
        user_id="u-mtm",
        mode="paper",
        period="inception",
        today=date(2024, 1, 3),
        eod=eod,
    )
    assert result.twr == Decimal("0.05")
    assert result.data_status != "нет данных"
