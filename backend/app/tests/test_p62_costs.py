from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.services.legal.catalog import load_ui_texts, reset_cache
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.total_costs.service import analyze_costs
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


def test_d62_texts() -> None:
    blob = " ".join(str(v).lower() for v in load_ui_texts()["d62"].values())
    assert "перейдите" not in blob
    assert "стоит купить" not in blob


def test_fifty_fees_sum_to_kopeck() -> None:
    ensure_account(account_id="c62", user_id="c62u", venue="bots", mode="paper")
    record_transaction(
        account_id="c62",
        user_id="c62u",
        mode="paper",
        venue="bots",
        external_id="dep",
        kind="deposit",
        instrument_id="CASH",
        ticker="CASH",
        qty="0",
        amount="100000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    for i in range(50):
        record_transaction(
            account_id="c62",
            user_id="c62u",
            mode="paper",
            venue="bots",
            external_id=f"fee{i}",
            kind="fee",
            instrument_id="CASH",
            ticker="CASH",
            qty="0",
            amount="1.25",
            ccy="RUB",
            event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
        )
    out = analyze_costs(user_id="c62u", mode="paper", year=2024)
    assert Decimal(out["total_rubles"]) == Decimal("62.50")
    ter = next(row for row in out["lines"] if row["id"] == "fund_ter")
    assert ter["data_status"] == "нет данных"
    assert out["data_status"] == "частично"


def test_api_flag() -> None:
    ensure_account(account_id="c62", user_id="c62api", venue="bots", mode="paper")
    bind_session_user("c62api")
    client = TestClient(app)
    assert client.get("/api/v1/portfolio/me/costs").status_code == 200
    set_global("qa_62_costs", False)
    assert client.get("/api/v1/portfolio/me/costs").status_code == 404
