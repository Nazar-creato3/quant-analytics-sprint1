from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.legal.catalog import load_ui_texts, reset_cache
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.pretrade_check.service import check_basket
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.risk_engine.series import put_series, reset as reset_series
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()
    reset_series()
    clear_session_user()
    reset_cache()


def teardown_function() -> None:
    get_book().reset()
    reset_series()
    reset_for_tests()
    clear_session_user()


def test_d60_texts() -> None:
    blob = " ".join(str(v).lower() for v in load_ui_texts()["d60"].values())
    assert "хорошая" not in blob
    assert "плохая" not in blob


def test_full_sell_drops_ticker() -> None:
    ensure_account(account_id="p60", user_id="p60u", venue="bots", mode="paper")
    record_transaction(
        account_id="p60",
        user_id="p60u",
        mode="paper",
        venue="bots",
        external_id="b1",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="10",
        amount="2500",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    put_series("SBER", [0.001] * 40)
    out = check_basket(
        user_id="p60u",
        mode="paper",
        trades=[{"ticker": "SBER", "side": "sell", "close": True}],
    )
    after_tickers = {c.get("ticker") for c in (out["after"].get("attribution") or {}).get("components") or []}
    assert "SBER" not in after_tickers or out["after"].get("var_95") is None
    assert out["blocks"]["tax"]["status"] == "будет доступно"
    for key in ("factors", "stress_rate", "futures", "goals", "bonds", "income", "look_through", "liquidity"):
        assert out["blocks"][key].get("reason")
        assert out["blocks"][key].get("status") != "будет доступно"


def test_api_flag() -> None:
    bind_session_user("p60api")
    client = TestClient(app)
    body = client.post("/api/v1/portfolio/me/pretrade", json={"trades": [], "mode": "paper"})
    assert body.status_code == 200
    set_global("qa_60_pretrade", False)
    assert client.post("/api/v1/portfolio/me/pretrade", json={"trades": []}).status_code == 404
