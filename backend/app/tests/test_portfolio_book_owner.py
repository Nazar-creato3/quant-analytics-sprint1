from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.services.portfolio_book.service import ensure_account, positions_for, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()


def teardown_function() -> None:
    get_book().reset()
    reset_for_tests()


def _trade(*, account_id: str, user_id: str, qty: str, amount: str) -> object:
    return record_transaction(
        account_id=account_id,
        user_id=user_id,
        mode="paper",
        venue="bots",
        external_id="bot:1",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty=qty,
        amount=amount,
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )


def test_same_external_id_does_not_steal_another_users_row():
    ensure_account(account_id="a-alice", user_id="alice", venue="bots", mode="paper")
    ensure_account(account_id="a-bob", user_id="bob", venue="bots", mode="paper")
    alice = _trade(account_id="a-alice", user_id="alice", qty="1", amount="100")
    bob = _trade(account_id="a-bob", user_id="bob", qty="7", amount="700")
    assert alice.user_id == "alice"
    assert bob.user_id == "bob"
    assert alice.id != bob.id
    assert positions_for(user_id="alice", mode="paper")[0].qty == Decimal("1")
    assert positions_for(user_id="bob", mode="paper")[0].qty == Decimal("7")
