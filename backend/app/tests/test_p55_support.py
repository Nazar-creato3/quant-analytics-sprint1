"""Prompt 55: a report stores no address and does not call Slack."""
from __future__ import annotations

import json
from pathlib import Path

from app.api.v1.endpoints.support_desk import post_support_report
from app.services.forecast_log.store import get_store
from app.services.product_analytics.metrics import metrics
from app.services.product_analytics.service import reset_analytics
from app.services.public_accuracy.service import public_accuracy
from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.subscription_billing.service import quote
from app.services.support_desk.service import (
    frequent,
    known_issues,
    report,
    reset_support,
    slack_notice,
    tickets,
)

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
REPO = Path(__file__).resolve().parents[3]


def setup_function() -> None:
    reset_for_tests()
    reset_support()
    reset_analytics()
    get_store().reset()


def teardown_function() -> None:
    reset_for_tests()
    reset_support()
    reset_analytics()
    get_store().reset()


def test_report_drops_personal_data_and_skips_slack() -> None:
    assert is_enabled("qa_support") is True
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_experiments") is False
    assert is_enabled("qa_preorder") is False
    assert is_enabled("qa_partners") is False
    assert public_accuracy()["accuracy"] == "нет данных"
    assert metrics()["activation"] == "нет данных"
    assert quote(user_id="p55", plan="personal", period="month")["amount"] == "10000"
    assert known_issues() == "нет данных"
    assert frequent() == "нет данных"
    rejected = post_support_report({"description": "ada@example.test", "email": "ada@example.test"})
    assert rejected["reason"] == "нет данных"
    assert tickets() == []
    stored = report(
        page="/account",
        version="local",
        request_id="req-1",
        errors=["e1"],
        description="кнопка не открылась",
        screenshot_consent=True,
        screenshot="raw-image",
    )
    assert stored["screenshot"] == "нет данных"
    assert stored["slack"] == "нет данных"
    assert stored["reply"] == "нет данных"
    blob = json.dumps(tickets())
    assert "raw-image" not in blob
    assert "@" not in blob
    assert frequent() == {"/account": "1"}
    notice = slack_notice()
    assert notice["status"] == "нет данных"
    assert "@" not in notice["text"]
    for rel in (
        "backend/app/services/support_desk/service.py",
        "frontend/src/lib/support-desk.ts",
        "docs/methodology/support-desk.md",
    ):
        text = (REPO / rel).read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN:
            assert phrase not in text


def test_support_status_needs_session_and_hides_slack() -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.tests.qa_session import auth_headers

    client = TestClient(app)
    assert client.get("/api/v1/support/status").status_code == 401
    body = client.get("/api/v1/support/status", headers=auth_headers("u1")).json()
    assert "slack" not in body
    assert "known_issues" in body
