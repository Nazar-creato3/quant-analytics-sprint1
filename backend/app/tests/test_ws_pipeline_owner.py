from __future__ import annotations

from app.api.v1.endpoints.websocket import (
    may_watch_pipeline_run,
    owner_email_for_pipeline_payload,
    pipeline_ws_channel,
)


def test_pipeline_ws_channel_is_per_email():
    assert pipeline_ws_channel("Alice@Test.com") == "pipeline:alice@test.com"
    assert pipeline_ws_channel("Alice@Test.com") != pipeline_ws_channel("bob@test.com")


def test_payload_without_owner_does_not_broadcast_globally():
    assert owner_email_for_pipeline_payload({"run_id": "r1"}) is None
    assert owner_email_for_pipeline_payload({"triggered_by": "alice@test.com"}) == "alice@test.com"
    assert owner_email_for_pipeline_payload({"triggered_by": "beat:alice@test.com"}) == "alice@test.com"


def test_foreign_run_is_not_watchable():
    meta = {"triggered_by": "alice@test.com", "report_id": "secret"}
    assert may_watch_pipeline_run(meta, email="alice@test.com", user_id="user-a") is True
    assert may_watch_pipeline_run(meta, email="bob@test.com", user_id="user-b") is False
    assert may_watch_pipeline_run(None, email="bob@test.com", user_id="user-b") is False
