"""Prompt 50: every planned event can be stored, and personal data cannot."""
from __future__ import annotations

import json
import os
from pathlib import Path

from app.api.v1.endpoints.product_analytics import post_analytics_event
from app.services.forecast_log.store import get_store
from app.services.product_analytics.service import (
    analytics_consent_text,
    plan,
    record_event,
    reset_analytics,
    set_analytics_consent_for_tests,
    stored_events,
    table_ddl,
)
from app.services.public_accuracy.service import public_accuracy
from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.subscription_billing.service import quote
from app.services.waitlist.service import open_fixture, unsubscribe
from app.services.waitlist.service import reset as reset_waitlist

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
REPO = Path(__file__).resolve().parents[3]
_PROPS: dict[str, dict[str, str]] = {
    "registration": {},
    "account_connect_success": {"venue": "moex"},
    "account_connect_error": {"venue": "tbank", "reason": "rejected"},
    "first_report_shown": {},
    "risk_view": {},
    "trade_check": {"result": "block"},
    "maneuver_proposed": {},
    "maneuver_viewed": {},
    "maneuver_edited": {},
    "maneuver_approved": {},
    "maneuver_rejected": {},
    "maneuver_executed": {"mode": "paper"},
    "paper_live_switch": {"mode": "live"},
    "profile_questionnaire_completed": {},
    "user_return": {},
    "unsubscribe": {},
}


def setup_function() -> None:
    reset_for_tests()
    reset_analytics()
    get_store().reset()
    reset_waitlist()


def teardown_function() -> None:
    reset_for_tests()
    reset_analytics()
    get_store().reset()
    reset_waitlist()


def test_unpublished_consent_and_empty_journal() -> None:
    assert is_enabled("qa_product_analytics") is True
    assert is_enabled("qa_preorder") is False
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_partners") is False
    assert is_enabled("qa_partner_ads") is False
    assert analytics_consent_text() == "нет данных"
    assert public_accuracy()["accuracy"] == "нет данных"
    assert quote(user_id="p50", plan="personal", period="month")["amount"] == "10000"
    dropped = record_event(
        name="registration",
        side="server",
        subject="user-1",
        properties={"email": "a@b.c"},
        consent=True,
        do_not_track=False,
    )
    assert dropped["status"] == "dropped"
    assert dropped["reason"] == "consent"
    assert stored_events() == []


def test_every_planned_event_is_stored_without_personal_data() -> None:
    set_analytics_consent_for_tests("fixture-consent")
    rejected = record_event(
        name="registration",
        side="server",
        subject="user-1",
        properties={"email": "a@b.c"},
        consent=True,
        do_not_track=False,
    )
    assert rejected["status"] == "rejected"
    assert stored_events() == []
    for row in plan():
        stored = record_event(
            name=row["name"],
            side=row["side"],
            subject="user-1",
            properties=_PROPS[row["name"]],
            consent=True,
            do_not_track=False,
        )
        assert stored["status"] == "stored"
    names = [row["name"] for row in stored_events()]
    assert names == [row["name"] for row in plan()]
    blocked = record_event(
        name="user_return",
        side="client",
        subject="user-1",
        properties={},
        consent=True,
        do_not_track=True,
    )
    assert blocked["reason"] == "dnt"
    assert len(stored_events()) == len(plan())
    posted = post_analytics_event(
        {
            "name": "risk_view",
            "subject": "user-1",
            "properties": {},
            "consent": True,
            "do_not_track": False,
        }
    )
    assert posted["status"] == "stored"
    via_client = post_analytics_event(
        {
            "name": "registration",
            "subject": "user-1",
            "properties": {},
            "consent": True,
            "do_not_track": False,
        }
    )
    assert via_client["status"] == "rejected"
    blob = json.dumps(stored_events())
    assert "user-1" not in blob
    assert "a@b.c" not in blob
    assert "@" not in blob
    assert "email" not in table_ddl()
    opened = open_fixture(
        email="a@b.c",
        name="n",
        broker="moex",
        portfolio_range="x",
        consent=True,
        honeypot="",
    )
    before = len(stored_events())
    unsubscribe(opened["token"])
    assert len(stored_events()) == before
    text = (REPO / "docs/analytics/tracking-plan.md").read_text(encoding="utf-8")
    for row in plan():
        assert row["name"] in text
    for rel in (
        "docs/analytics/tracking-plan.md",
        "backend/app/services/product_analytics/service.py",
        "frontend/src/lib/product-analytics.ts",
    ):
        body = (REPO / rel).read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN:
            assert phrase not in body
    os.environ["FF_QA_PRODUCT_ANALYTICS"] = "0"
    assert record_event(
        name="registration",
        side="server",
        subject="user-1",
        properties={},
        consent=True,
        do_not_track=False,
    )["status"] == "off"
