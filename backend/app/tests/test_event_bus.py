"""Prompt 07: event bus idempotency, DLQ, safe templates, circuit flow."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.event_bus.bus import get_bus, publish_event
from app.services.event_bus.notifications import (
    assert_templates_safe,
    circuit_state,
    get_store,
    reset_side_effects,
)
from app.services.qa.feature_flags import reset_for_tests


@pytest.fixture(autouse=True)
def _reset():
    reset_for_tests()
    get_bus().reset()
    reset_side_effects()
    yield
    get_bus().reset()
    reset_side_effects()
    reset_for_tests()


def test_templates_have_no_trade_advice():
    assert_templates_safe()


def test_idempotent_publish():
    a = publish_event("bot.circuit_breaker", {"reason": "dd", "user_id": "u1"}, idempotency_key="k1")
    b = publish_event("bot.circuit_breaker", {"reason": "dd", "user_id": "u1"}, idempotency_key="k1")
    assert a is not None and b is not None
    assert a.id == b.id
    assert get_bus().metrics()["stream"] == 1
    assert len(get_store().for_user("u1")) == 1


def test_retry_then_dlq():
    bus = get_bus()

    def boom(_msg: dict) -> None:
        raise RuntimeError("fail")

    bus.subscribe("risk.warning", boom)
    env = publish_event("risk.warning", {"user_id": "u"})
    assert env is not None
    bus.fail(env.id)
    bus.fail(env.id)
    bus.fail(env.id)
    assert get_bus().metrics()["dlq"] >= 1


def test_circuit_breaker_side_effects():
    publish_event(
        "bot.circuit_breaker",
        {"reason": "drawdown", "bot_id": "grid-1", "user_id": "u1"},
    )
    state = circuit_state()
    assert "grid-1" in state["paused_bots"]
    assert "bot_circuit_breaker" in state["banners"]
    assert state["chat_context"]
    notes = get_store().for_user("u1")
    assert "купите" not in notes[0].text.lower()
    assert "продайте" not in notes[0].text.lower()


def test_sync_failed_and_risk():
    publish_event("account.sync_failed", {"account_id": "acc-1", "venue": "tbank", "user_id": "u"})
    publish_event("risk.limit_breached", {"limit": "var", "user_id": "u"})
    state = circuit_state()
    assert state["account_status"]["acc-1"] == "error"
    assert "risk_limit" in state["banners"]


def test_unknown_event_rejected():
    with pytest.raises(ValueError):
        publish_event("not.a.real.event", {})


def test_notifications_api():
    publish_event("bot.paused", {"bot_id": "b", "user_id": "u9"})
    from app.tests.qa_session import bind_session_user, clear_session_user

    bind_session_user("u9")
    client = TestClient(app)
    res = client.get("/api/v1/notifications", params={"user_id": "u9"})
    clear_session_user()
    assert res.status_code == 200
    assert res.json()["count"] >= 1
