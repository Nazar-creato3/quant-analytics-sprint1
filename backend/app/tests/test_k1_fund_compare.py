"""K1 numbers in the K6 fund block. Does not import FastAPI app (skfolio stays in 65)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.fund_report.metrics import fund_metrics
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.portfolio_report.service import assemble
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()


def teardown_function() -> None:
    get_book().reset()
    reset_for_tests()


def test_fund_metrics_k1_placeholder_until_assemble() -> None:
    out = fund_metrics([0.01, -0.02, 0.015])
    assert out["k1"]["status"] == "pending"
    assert out["k1"]["alternatives"] == []


def test_assemble_fund_k1_uses_simple_alts() -> None:
    ensure_account(account_id="k1rep", user_id="k1-report", venue="bots", mode="paper")
    record_transaction(
        account_id="k1rep",
        user_id="k1-report",
        mode="paper",
        venue="bots",
        external_id="k1-dep",
        kind="deposit",
        instrument_id="CASH",
        ticker="CASH",
        qty="0",
        amount="100000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    fund = assemble(user_id="k1-report", mode="paper")["fund"]
    assert "k1" in fund
    assert "alternatives" in fund["k1"]
    assert fund["k1"]["status"] in {"ok", "частично", "нет данных", "off"}
