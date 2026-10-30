"""Prompt 19: connect-capital paths, sync stages, funnel without PII."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.onboarding.service import (
    STAGES,
    connect_key,
    funnel_snapshot,
    reset,
    start,
    sync_once,
    try_demo,
)
from app.services.qa.feature_flags import reset_for_tests, set_global


def setup_function() -> None:
    reset_for_tests()
    reset()


def teardown_function() -> None:
    reset()
    reset_for_tests()


def test_demo_opens_report_paper_only():
    body = try_demo("u1")
    assert body["ready_report"] is True
    assert body["next"] == "/portfolio-report"
    assert body["mode"] == "paper"
    assert body["stages_done"] == list(STAGES)
    names = [e["name"] for e in funnel_snapshot()]
    assert "connect_ok" in names
    assert "report_opened" in names
    assert all("@" not in e["session"] for e in funnel_snapshot())


def test_partner_deferred():
    body = start("u1", "partner")
    assert body["available"] is False
    assert "25" in body["reason"]


def test_key_errors_and_partial_history():
    start("u1", "have_account", "tbank")
    bad = connect_key("u1", venue="tbank", accepted=False)
    assert bad["error"] == "bad_key"
    assert "Ключ не принят" in bad["error_text"]
    extra = connect_key("u1", venue="tbank", accepted=True, withdraw_allowed=True)
    assert extra["error"] == "extra_rights"
    down = connect_key("u1", venue="tbank", accepted=True, venue_up=False)
    assert down["error"] == "venue_down"
    ok = connect_key("u1", venue="tbank", accepted=True, has_history=False)
    assert ok["partial"] is True
    assert ok["error"] == "no_history"


def test_sync_stages_then_report():
    start("u1", "have_account", "tbank")
    connect_key("u1", venue="tbank", accepted=True)
    last = None
    for _ in STAGES:
        last = sync_once("u1")
    assert last is not None
    assert last["ready_report"] is True
    assert last["stages_done"] == list(STAGES)
    slow = start("u2", "have_account", "tbank")
    connect_key("u2", venue="tbank", accepted=True)
    hung = sync_once("u2", slow=True)
    assert hung["error"] == "sync_slow"
    assert hung["next"] == "/portfolio-report"


def test_api_and_flag():
    from app.tests.qa_session import bind_session_user, clear_session_user

    client = TestClient(app)
    anon = client.get("/api/v1/onboarding/funnel")
    assert anon.status_code == 401
    bind_session_user("demo")
    demo = client.post("/api/v1/onboarding/demo", params={"user_id": "demo"})
    assert demo.status_code == 200
    assert demo.json()["next"] == "/portfolio-report"
    funnel = client.get("/api/v1/onboarding/funnel")
    assert funnel.status_code == 200
    assert funnel.json()["events"]
    set_global("qa_onboarding", False)
    assert client.get("/api/v1/onboarding/status").status_code == 404
    clear_session_user()
