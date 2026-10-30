"""Prompt 23: channels, quiet hours, telegram inform-only, no secrets."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.event_bus.notifications import assert_templates_safe, reset_side_effects
from datetime import timedelta

from app.services.notify_center.service import (
    bind_telegram,
    command,
    deliver,
    issue_unsubscribe_token,
    reset,
    set_prefs,
    telegram_code,
    unsubscribe_email,
)
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()
    reset()
    reset_side_effects()


def teardown_function() -> None:
    reset()
    reset_side_effects()
    reset_for_tests()


def test_quiet_skips_noncritical_critical_retries():
    set_prefs(user_id="u", channels=["in_app", "email"], types=None, quiet_from=22, quiet_to=7)
    skip = deliver(user_id="u", event_name="bot.paused", payload={"bot_id": "1"}, hour_utc=23)
    assert skip["skipped"] == "quiet"
    crit = deliver(user_id="u", event_name="risk.limit_breached", payload={"limit": "HHI"}, hour_utc=23)
    assert "in_app" in crit["delivered"]
    assert crit["critical"] is True
    assert crit["retries"]
    assert "купи" not in crit["text"].lower()
    assert_templates_safe()


def test_telegram_inform_only_and_api():
    code = telegram_code(user_id="u")["code"]
    assert len(code) == 32
    assert bind_telegram(code=code)["bound"] is True
    blocked = command(user_id="u", text="/confirm buy")
    assert blocked["ok"] is False
    st = command(user_id="u", text="/status")
    assert st["creates_order"] is False
    assert "token" not in st["text"].lower()
    from app.tests.qa_session import bind_session_user, clear_session_user

    bind_session_user("u")
    client = TestClient(app)
    ev = client.post("/api/v1/notifications/deliver", json={"user_id": "u", "event_name": "account.sync_failed", "payload": {"venue": "tbank"}})
    assert ev.status_code == 200
    listed = client.get("/api/v1/notifications", params={"user_id": "u"}).json()
    assert listed["count"] >= 1
    clear_session_user()


def test_deliver_email_errors_are_only_for_that_user():
    set_prefs(user_id="alice", channels=["email"], types=None, quiet_from=None, quiet_to=None)
    set_prefs(user_id="bob", channels=["email"], types=None, quiet_from=None, quiet_to=None)
    sent = deliver(user_id="alice", event_name="bot.paused", payload={"bot_id": "1"})
    assert unsubscribe_email(token=sent["unsubscribe_token"])["unsubscribed"] is True
    deliver(user_id="alice", event_name="bot.paused", payload={"bot_id": "1"})
    bob = deliver(user_id="bob", event_name="bot.paused", payload={"bot_id": "2"})
    assert all(err.get("user_id") == "bob" for err in bob["email_errors"])
    assert not any(err.get("user_id") == "alice" for err in bob["email_errors"])


def test_unsubscribe_and_expired_code_refuse():
    set_prefs(user_id="u", channels=["email"], types=None, quiet_from=None, quiet_to=None)
    sent = deliver(user_id="u", event_name="bot.paused", payload={"bot_id": "1"})
    assert unsubscribe_email(token=sent["unsubscribe_token"])["unsubscribed"] is True
    stale = issue_unsubscribe_token(user_id="u", ttl=timedelta(seconds=-1))
    assert unsubscribe_email(token=stale)["reason"] == "код истёк"
    expired = telegram_code(user_id="u", ttl=timedelta(seconds=-1))
    assert bind_telegram(code=expired["code"])["reason"] == "код истёк"
