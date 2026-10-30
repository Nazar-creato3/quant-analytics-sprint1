"""Baseline letter а: register/login/logout, 401/403 isolation, crypto codes."""
from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.core.security import (
    access_jti_revoked,
    create_access_token,
    decode_token,
    reset_revoked_access_jti,
    revoke_access_jti,
)
from app.main import app
from app.services.chat.qa_registry import invoke, journal, reset as reset_journal
from app.services.notify_center.service import (
    bind_telegram,
    deliver,
    issue_unsubscribe_token,
    reset as reset_notify,
    set_prefs,
    telegram_code,
    unsubscribe_email,
)
from app.services.qa.feature_flags import reset_for_tests
from app.services.risk_engine.shadow import reset_diffs, shadow_compare
from app.tests.qa_session import auth_headers


def setup_function() -> None:
    reset_for_tests()
    reset_notify()
    reset_journal()
    reset_diffs()
    reset_revoked_access_jti()


def teardown_function() -> None:
    reset_notify()
    reset_journal()
    reset_diffs()
    reset_revoked_access_jti()
    reset_for_tests()


def test_telegram_codes_are_crypto_random_and_expire() -> None:
    first = telegram_code(user_id="alice", ttl=timedelta(minutes=15))
    second = telegram_code(user_id="bob", ttl=timedelta(minutes=15))
    assert first["code"] != second["code"]
    assert len(first["code"]) == 32
    assert "expires_at" in first
    assert bind_telegram(code=first["code"])["bound"] is True
    expired = telegram_code(user_id="carol", ttl=timedelta(seconds=-1))
    assert bind_telegram(code=expired["code"]) == {"bound": False, "reason": "код истёк"}
    assert bind_telegram(code="missing") == {"bound": False, "reason": "нет данных"}


def test_unsubscribe_token_is_crypto_random_and_expires() -> None:
    set_prefs(user_id="alice", channels=["email"], types=None, quiet_from=None, quiet_to=None)
    sent = deliver(user_id="alice", event_name="bot.paused", payload={"bot_id": "1"})
    token = sent["unsubscribe_token"]
    assert len(token) >= 32
    assert unsubscribe_email(token=token)["unsubscribed"] is True
    assert unsubscribe_email(token=token)["unsubscribed"] is False
    stale = issue_unsubscribe_token(user_id="bob", ttl=timedelta(seconds=-1))
    assert unsubscribe_email(token=stale) == {"unsubscribed": False, "reason": "код истёк"}


def test_logout_revokes_access_jti() -> None:
    token = create_access_token("alice@example.com", extra_claims={"user_id": "alice"})
    payload = decode_token(token)
    jti = payload["jti"]
    assert access_jti_revoked(jti) is False
    revoke_access_jti(jti)
    assert access_jti_revoked(jti) is True
    client = TestClient(app)
    res = client.get(
        "/api/v1/risk/backtests",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401


def test_api_refuses_foreign_risk_journal_and_bad_bind() -> None:
    client = TestClient(app)
    headers = auth_headers("alice")
    for path in (
        "/api/v1/risk/backtests",
        "/api/v1/risk/shadow",
        "/api/v1/qa-tools/journal",
        "/api/v1/act/journal",
        "/api/v1/notifications/telegram/code",
    ):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=headers).status_code in {200, 404}
        assert client.get(path, params={"user_id": "bob"}, headers=headers).status_code == 403

    bad_bind = client.post("/api/v1/notifications/telegram/bind", json={"code": "nope"})
    assert bad_bind.status_code in {403, 404}
    bad_unsub = client.post("/api/v1/notifications/email/unsubscribe", params={"token": "nope"})
    assert bad_unsub.status_code in {403, 404}

    invoke(name="qa_portfolio_report", user_id="alice")
    invoke(name="qa_portfolio_report", user_id="bob")
    shadow_compare([0.01, -0.02, 0.03], user_id="alice")
    shadow_compare([0.04, -0.01, 0.02], user_id="bob")
    assert all(row["user_id"] == "alice" for row in journal(user_id="alice"))
    assert {row["user_id"] for row in journal()} == {"alice", "bob"}
    mine = client.get("/api/v1/risk/shadow", headers=headers).json()
    assert all(row.get("user_id") == "alice" for row in mine.get("rows", []))
