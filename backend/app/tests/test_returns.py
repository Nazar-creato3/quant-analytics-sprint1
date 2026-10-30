"""Prompt 08: TWR/MWR from book, official close, incomplete history."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests
from app.tests.qa_session import bind_session_user, clear_session_user
from app.services.quant_math.book import time_weighted_return
from app.services.returns.service import as_dict, choose_benchmark, compute_returns, period_start
from app.services.returns.reconcile import compare


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()


def teardown_function() -> None:
    get_book().reset()
    reset_for_tests()
    clear_session_user()


def _deposit_and_div(user: str = "u1") -> None:
    ensure_account(account_id="p1", user_id=user, venue="bots", mode="paper")
    record_transaction(
        account_id="p1",
        user_id=user,
        mode="paper",
        venue="bots",
        external_id="d1",
        kind="deposit",
        instrument_id="CASH",
        ticker="CASH",
        qty="0",
        amount="100",
        ccy="RUB",
        event_time=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    record_transaction(
        account_id="p1",
        user_id=user,
        mode="paper",
        venue="bots",
        external_id="div1",
        kind="dividend",
        instrument_id="SBER",
        ticker="SBER",
        qty="0",
        amount="10",
        ccy="RUB",
        event_time=datetime(2024, 6, 15, tzinfo=timezone.utc),
    )


def test_e46_13_trade_pnl_marks_to_official_close_not_cash_amount():
    from app.services.market_data.eod import EodRow

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
    # One deposit, no later flows: money-weighted equals time-weighted for the period.
    assert result.mwr is not None and abs(result.mwr - Decimal("0.05")) < Decimal("0.0001")
    assert result.data_status == "ok"
    _deposit_and_div()
    result = compute_returns(
        user_id="u1",
        mode="paper",
        period="inception",
        today=date(2024, 6, 20),
        start_value=Decimal("100"),
    )
    expected = time_weighted_return([(Decimal("100"), Decimal("110"))])
    assert result.twr == expected
    assert result.dietz_used is False
    assert result.annualized is False


def test_incomplete_history_flag():
    _deposit_and_div()
    result = compute_returns(
        user_id="u1",
        mode="paper",
        period="year",
        today=date(2024, 6, 20),
    )
    assert result.incomplete is True
    assert as_dict(result)["load_report_hint"]


def test_annualize_only_over_year():
    start = period_start("year", date(2025, 6, 1))
    assert start == date(2025, 1, 1)
    _deposit_and_div()
    result = compute_returns(
        user_id="u1",
        mode="paper",
        period="custom",
        custom_from=date(2022, 1, 1),
        today=date(2024, 6, 20),
        start_value=Decimal("100"),
    )
    assert result.annualized is True


def test_benchmark_rules():
    assert choose_benchmark(["BTC-USD"], ["USD"])[0] == "BTC-USD"
    assert "proxy" in choose_benchmark(["AAPL"], ["USD"])[1].lower()
    assert choose_benchmark(["SBER"], ["RUB"])[0] == "MCFTR"


def test_reconcile_tolerance():
    out = compare({"twr": "0.10", "mwr": "0.10"}, {"twr": "0.1005", "mwr": "0.10"})
    assert out["ok"] is True
    bad = compare({"twr": "0.10", "mwr": "0.10"}, {"twr": "0.12", "mwr": "0.10"})
    assert bad["ok"] is False


def test_returns_api():
    _deposit_and_div("api")
    bind_session_user("api")
    client = TestClient(app)
    res = client.get("/api/v1/returns", params={"user_id": "api", "mode": "paper"})
    assert res.status_code == 200
    body = res.json()
    assert body["source"].startswith("quant_math")
    assert "twr_label" in body
