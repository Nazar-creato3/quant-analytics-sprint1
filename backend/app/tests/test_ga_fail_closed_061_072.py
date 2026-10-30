"""GA-061…072: returns MWR/publish and portfolio except-pass fail closed."""
from __future__ import annotations

import inspect
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests
from app.services.returns.service import compute_returns


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()


def teardown_function() -> None:
    get_book().reset()
    reset_for_tests()


def _cash_book(user: str) -> None:
    ensure_account(account_id=f"p-{user}", user_id=user, venue="bots", mode="paper")
    record_transaction(
        account_id=f"p-{user}",
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


def test_ga061_062_mwr_failure_does_not_copy_twr(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("irr down")

    monkeypatch.setattr("app.services.returns.service.money_weighted_return", boom)
    monkeypatch.setattr("app.services.returns.service.publish_event", boom)
    _cash_book("ga061")
    result = compute_returns(
        user_id="ga061",
        mode="paper",
        period="inception",
        today=date(2024, 6, 20),
        start_value=Decimal("100"),
    )
    assert result.twr is not None
    assert result.mwr is None
    assert result.data_status != "нет данных"
    assert result.data_status == "недостаточно данных"
    assert result.reason == "MWR не посчитан"


def test_ga_portfolio_except_pass_gone() -> None:
    from app.services.portfolio import (
        barrier_close,
        cancel_maneuver,
        cost_basis,
        entry_snapshot,
        expiration_close,
        flatten,
        metrics,
    )

    for mod, needle in (
        (expiration_close, "expiration lot/plan close failed"),
        (flatten, "flatten lot/plan close failed"),
        (cancel_maneuver, "feature kill record failed"),
        (barrier_close, "close barrier anyway"),
        (metrics, "cached metrics invalid"),
        (cost_basis, "lot snapshot unavailable"),
        (entry_snapshot, "regime at entry unavailable"),
    ):
        src = inspect.getsource(mod)
        assert "except Exception:\n            pass" not in src
        assert "except Exception:\n        pass" not in src
        assert needle in src
