"""59: timing and trade-cost report from returns + book + K1."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.services.decisions_report.service import analyze_decisions
from app.services.legal.catalog import load_ui_texts, reset_cache
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()
    clear_session_user()
    reset_cache()


def teardown_function() -> None:
    get_book().reset()
    reset_for_tests()
    clear_session_user()


def _txn(user: str, ext: str, kind: str, **kwargs: object) -> None:
    record_transaction(
        account_id="d59",
        user_id=user,
        mode="paper",
        venue="bots",
        external_id=ext,
        kind=kind,  # type: ignore[arg-type]
        instrument_id=str(kwargs.get("instrument_id") or "CASH"),
        ticker=str(kwargs.get("ticker") or "CASH"),
        qty=str(kwargs.get("qty") or "0"),
        amount=str(kwargs.get("amount") or "0"),
        ccy="RUB",
        event_time=kwargs["event_time"],  # type: ignore[arg-type]
    )


def test_d59_texts_neutral() -> None:
    pack = load_ui_texts()["d59"]
    blob = " ".join(str(v).lower() for v in pack.values())
    for word in ("стоит купить", "плохо", "выгодно", "ошибка"):
        assert word not in blob
    assert pack["title"]


def test_hold_only_zero_time_and_trade() -> None:
    ensure_account(account_id="d59", user_id="d59-hold", venue="bots", mode="paper")
    _txn("d59-hold", "dep", "deposit", amount="100000", event_time=datetime(2024, 1, 2, tzinfo=timezone.utc))
    out = analyze_decisions(user_id="d59-hold", mode="paper", date_to=datetime(2024, 1, 31).date())
    assert Decimal(out["trade_cost"]["rubles"]) == Decimal("0.00")
    assert out["time_cost"]["rubles"] in {"0.00", "0"}
    assert out["total_rubles"] in {"0.00", "0"}


def test_disposition_known_pgr_plr() -> None:
    ensure_account(account_id="d59", user_id="d59-disp", venue="bots", mode="paper")
    _txn("d59-disp", "dep", "deposit", amount="1000", event_time=datetime(2024, 1, 2, tzinfo=timezone.utc))
    _txn(
        "d59-disp",
        "b1",
        "trade",
        ticker="SBER",
        instrument_id="SBER",
        qty="10",
        amount="1000",
        event_time=datetime(2024, 1, 3, tzinfo=timezone.utc),
    )
    _txn(
        "d59-disp",
        "s1",
        "trade",
        ticker="SBER",
        instrument_id="SBER",
        qty="-10",
        amount="1200",
        event_time=datetime(2024, 1, 10, tzinfo=timezone.utc),
    )
    out = analyze_decisions(user_id="d59-disp", mode="paper")
    assert out["disposition"]["pgr"] == "1.0000"
    assert out["disposition"]["plr"] is None  # нет убыточных исходов
    assert out["thin"] is True
    assert out["disposition"]["reason"] == "мало данных для вывода"


def test_api_and_flag() -> None:
    ensure_account(account_id="d59", user_id="d59-api", venue="bots", mode="paper")
    _txn("d59-api", "dep", "deposit", amount="50000", event_time=datetime(2024, 1, 2, tzinfo=timezone.utc))
    bind_session_user("d59-api")
    client = TestClient(app)
    ok = client.get("/api/v1/portfolio/me/decisions", params={"mode": "paper"})
    assert ok.status_code == 200
    assert "time_cost" in ok.json()
    set_global("qa_59_decisions", False)
    off = client.get("/api/v1/portfolio/me/decisions")
    assert off.status_code == 404
