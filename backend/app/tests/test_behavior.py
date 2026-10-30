"""Prompt 15: disposition on synthetic histories; no trade advice."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.behavior.service import FORBIDDEN, analyze_trades, weekly_text
from app.services.event_bus.notifications import weekly_user_note
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()


def teardown_function() -> None:
    reset_for_tests()


def _roundtrips(*, wins: int, losses: int, start: datetime) -> list[dict]:
    trades = []
    t = start
    i = 0
    for _ in range(wins):
        trades.append({"ticker": "SBER", "side": "buy", "qty": 1, "price": 100, "time": t})
        t += timedelta(days=10)
        trades.append({"ticker": "SBER", "side": "sell", "qty": 1, "price": 110, "time": t})
        t += timedelta(days=1)
        i += 1
    for _ in range(losses):
        trades.append({"ticker": "GAZP", "side": "buy", "qty": 1, "price": 100, "time": t})
        t += timedelta(days=10)
        trades.append({"ticker": "GAZP", "side": "sell", "qty": 1, "price": 90, "time": t})
        t += timedelta(days=1)
    return trades


def test_insufficient_sample():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out = analyze_trades(_roundtrips(wins=2, losses=0, start=t0))
    assert out["insufficient"] is True
    assert out["signals"] == []
    assert "минимум" in out["text"]


def test_disposition_known_pattern():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    high = analyze_trades(_roundtrips(wins=8, losses=0, start=t0))
    assert high["insufficient"] is False
    assert high["realized_gain_share"] == 1.0
    assert high["signals"][0]["present"] is True
    balanced = analyze_trades(_roundtrips(wins=4, losses=4, start=t0))
    assert balanced["signals"][0]["present"] is False
    low = analyze_trades(_roundtrips(wins=0, losses=8, start=t0))
    assert low["realized_loss_share"] == 1.0
    assert low["signals"][0]["present"] is False
    blob = (high["text"] + balanced["text"] + low["text"]).lower()
    for word in FORBIDDEN:
        assert word not in blob


def test_api_empty_user():
    from app.tests.qa_session import bind_session_user, clear_session_user

    bind_session_user("nobody")
    client = TestClient(app)
    body = client.get("/api/v1/behavior", params={"user_id": "nobody"}).json()
    assert body["source"] == "behavior"
    assert body["insufficient"] is True
    clear_session_user()
    letter = weekly_text(user_id="nobody")
    assert letter == weekly_user_note("nobody")
    assert "минимум" in letter
