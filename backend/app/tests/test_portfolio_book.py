"""Prompt 05: one book, paper/live split, official_close valuation."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.bots.common import record_paper_trade
from app.services.market_data.eod import EodRow
from app.services.portfolio_book.service import (
    assert_mode,
    ensure_account,
    positions_for,
    record_bot_trade,
    record_transaction,
    value_positions,
)
from app.services.portfolio_book.store import BookModeError, get_book
from app.services.qa.feature_flags import reset_for_tests


@pytest.fixture(autouse=True)
def _reset():
    reset_for_tests()
    get_book().reset()
    yield
    get_book().reset()
    reset_for_tests()


def test_paper_and_live_do_not_mix():
    ensure_account(account_id="p1", user_id="u1", venue="bots", mode="paper")
    ensure_account(account_id="l1", user_id="u1", venue="tbank", mode="live")
    record_transaction(
        account_id="p1",
        user_id="u1",
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
    with pytest.raises(BookModeError):
        record_transaction(
            account_id="p1",
            user_id="u1",
            mode="live",
            venue="bots",
            external_id="t2",
            kind="trade",
            instrument_id="SBER",
            ticker="SBER",
            qty="1",
            amount="1",
            ccy="RUB",
            event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
    assert len(positions_for(user_id="u1", mode="paper")) == 1
    assert positions_for(user_id="u1", mode="live") == []
    with pytest.raises(BookModeError):
        assert_mode("mixed")


def test_idempotent_external_id():
    ensure_account(account_id="p1", user_id="u1", venue="bots", mode="paper")
    a = record_transaction(
        account_id="p1",
        user_id="u1",
        mode="paper",
        venue="bots",
        external_id="same",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="2",
        amount="200",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    b = record_transaction(
        account_id="p1",
        user_id="u1",
        mode="paper",
        venue="bots",
        external_id="same",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="99",
        amount="1",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    assert a.id == b.id
    assert positions_for(user_id="u1", mode="paper")[0].qty == Decimal("2")


def test_correction_is_new_version():
    ensure_account(account_id="p1", user_id="u1", venue="bots", mode="paper")
    record_transaction(
        account_id="p1",
        user_id="u1",
        mode="paper",
        venue="bots",
        external_id="x",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="2",
        amount="200",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    get_book().correct_txn("bots", "x", user_id="u1", qty=Decimal("3"))
    assert len(get_book().transactions(user_id="u1", mode="paper")) == 2
    assert positions_for(user_id="u1", mode="paper")[0].qty == Decimal("3")


def test_bitemporal_as_of():
    ensure_account(account_id="p1", user_id="u1", venue="bots", mode="paper")
    record_transaction(
        account_id="p1",
        user_id="u1",
        mode="paper",
        venue="bots",
        external_id="early",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="1",
        amount="100",
        ccy="RUB",
        event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        recorded_at=datetime(2024, 1, 10, tzinfo=timezone.utc),
    )
    later = positions_for(
        user_id="u1",
        mode="paper",
        as_of_event=datetime(2024, 1, 2, tzinfo=timezone.utc),
        as_of_recorded=datetime(2024, 1, 5, tzinfo=timezone.utc),
    )
    assert later == []
    known = positions_for(
        user_id="u1",
        mode="paper",
        as_of_event=datetime(2024, 1, 2, tzinfo=timezone.utc),
        as_of_recorded=datetime(2024, 1, 11, tzinfo=timezone.utc),
    )
    assert len(known) == 1


def test_valuation_official_close():
    ensure_account(account_id="p1", user_id="u1", venue="bots", mode="paper")
    record_transaction(
        account_id="p1",
        user_id="u1",
        mode="paper",
        venue="bots",
        external_id="v",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="2",
        amount="200",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    eod = {
        "SBER": EodRow(
            instrument_id="SBER",
            session_date=date(2024, 1, 2),
            official_close=Decimal("50"),
            last_close=Decimal("999"),
            volume=None,
            source="iss_moex",
            board="TQBR",
            license_tag="internal_only",
            as_of=date(2024, 1, 2),
        )
    }
    valued = value_positions(positions_for(user_id="u1", mode="paper"), eod)
    assert valued[0]["value"] == "100"
    assert valued[0]["price_type"] == "official_close"


def test_bot_trade_visible_in_book():
    record_paper_trade(
        {"user_id": "u9", "symbol": "AAPL"},
        bot_id="b1",
        side="buy",
        price=10.0,
        quantity=3.0,
    )
    pos = positions_for(user_id="u9", mode="paper")
    assert pos[0].ticker == "AAPL"
    assert pos[0].qty == Decimal("3.0")


def test_book_api_requires_mode():
    record_bot_trade(
        user_id="u2",
        ticker="MSFT",
        qty="1",
        amount="10",
        ccy="USD",
        side="buy",
        external_id="api-1",
    )
    from app.tests.qa_session import bind_session_user, clear_session_user

    bind_session_user("u2")
    client = TestClient(app)
    res = client.get("/api/v1/book/positions", params={"user_id": "u2", "mode": "paper"})
    assert res.status_code == 200
    assert res.json()["count"] == 1
    bad = client.get("/api/v1/book/positions", params={"user_id": "u2", "mode": "all"})
    assert bad.status_code == 422
    clear_session_user()
