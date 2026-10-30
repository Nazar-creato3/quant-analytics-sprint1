"""Prompt 48: unpublished consent blocks storage; the fixture can confirm and unsubscribe."""
from __future__ import annotations

import os
from pathlib import Path

from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.subscription_billing.service import quote
from app.services.waitlist.service import (
    confirm,
    founder_export,
    join,
    notices,
    open_fixture,
    public_status,
    request_preorder,
    reset,
    unsubscribe,
)

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")


def setup_function() -> None:
    reset_for_tests()
    reset()


def teardown_function() -> None:
    reset_for_tests()
    reset()


def _fixture(email: str, *, consent: bool = True, honeypot: str = "") -> dict:
    return open_fixture(
        email=email,
        name=None,
        broker="unset",
        portfolio_range="нет данных",
        consent=consent,
        honeypot=honeypot,
    )


def test_flags_and_public_join_store_nothing() -> None:
    assert is_enabled("qa_waitlist") is True
    assert is_enabled("qa_preorder") is False
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_partners") is False
    # Price list is published (founder pricing); checkout/payment stay gated separately.
    assert quote(user_id="p48", plan="personal", period="month")["amount"] == "10000"
    assert quote(user_id="p48", plan="personal", period="month")["status"] == "off"
    assert quote(user_id="p48", plan="personal", period="month")["checkout"] == "off"
    blocked = join(email="a@example.com", name=None, broker="unset", portfolio_range="нет данных", consent=True, honeypot="")
    assert blocked["status"] == "rejected"
    assert blocked["consent"] == "нет данных"
    assert founder_export() == []


def test_fixture_confirms_once_and_unsubscribes() -> None:
    opened = _fixture("person@example.com")
    assert opened["status"] == "pending"
    assert opened["mail"] == "нет данных"
    assert "@" not in notices()[0]["text"]
    assert "person@example.com" not in notices()[0]["text"]
    assert confirm(opened["token"])["status"] == "confirmed"
    assert confirm(opened["token"])["status"] == "confirmed"
    assert len(notices()) == 1
    assert unsubscribe(opened["token"])["status"] == "unsubscribed"
    assert confirm(opened["token"])["status"] == "unsubscribed"
    assert public_status()["consent"] == "нет данных"
    assert "email" not in public_status()
    exported = founder_export()
    assert exported[0]["email"] == "person@example.com"
    assert exported[0]["status"] == "unsubscribed"


def test_spam_limit_and_preorder_stay_off() -> None:
    assert _fixture("spam@example.com", honeypot="filled")["reason"] == "spam"
    assert _fixture("no@example.com", consent=False)["reason"] == "consent"
    for index in range(5):
        assert _fixture(f"n{index}@example.com")["status"] == "pending"
    assert _fixture("overflow@example.com")["reason"] == "limit"
    opened = _fixture("early@example.com")
    assert request_preorder(plan="personal", token=opened.get("token", "missing"))["status"] in {"rejected", "off"}
    confirmed = None
    reset()
    opened = _fixture("ready@example.com")
    confirm(opened["token"])
    held = request_preorder(plan="personal", token=opened["token"])
    assert held["status"] == "off"
    assert held["amount"] == "нет данных"
    assert held["subscription"] == "10000"
    assert held["provider"] == "off"
    os.environ["FF_QA_PREORDER"] = "1"
    forced = request_preorder(plan="personal", token=opened["token"])
    assert forced["provider"] == "off"
    assert forced["amount"] == "нет данных"
    assert confirmed is None


def test_waitlist_texts_omit_forbidden_phrases() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "app" / "services" / "waitlist" / "service.py").read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN:
        assert phrase not in text
