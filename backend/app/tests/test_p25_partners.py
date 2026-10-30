"""Prompt 25: partner path stays off; R5 discount only after a funded broker status."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.onboarding.service import reset as reset_onboarding
from app.services.onboarding.service import start
from app.services.partners.service import (
    apply_broker_event,
    disclosure_text,
    public_view,
    reconcile,
    record_click,
    register_partner,
    reset,
    subscription_handoff,
)
from app.services.qa.feature_flags import is_enabled, reset_for_tests, set_global

_FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")


def setup_function() -> None:
    reset_for_tests()
    reset()
    reset_onboarding()


def teardown_function() -> None:
    reset_for_tests()
    reset()
    reset_onboarding()


def test_flag_off_hides_offer_and_keeps_onboarding():
    assert is_enabled("qa_partners") is False
    assert is_enabled("qa_partner_ads") is False
    assert is_enabled("qa_act_live") is False
    view = public_view()
    assert view["status"] == "off"
    assert view["disclosure"] == "нет данных"
    assert disclosure_text() == "нет данных"
    body = start("user-25", "partner")
    assert body["available"] is False
    assert "25" in body["reason"]
    text = Path(__file__).resolve().parents[1].joinpath("services/partners/service.py").read_text(encoding="utf-8").lower()
    for phrase in _FORBIDDEN:
        assert phrase not in text


def test_click_status_discount_and_reconcile_without_user_in_the_link():
    set_global("qa_partners", True)
    user = "user-25-secret"
    register_partner(partner_id="desk", link="https://example.invalid/open")
    with pytest.raises(ValueError, match="соглас"):
        record_click(user_id=user, partner_id="desk", source="cabinet", consent=False)
    clicked = record_click(user_id=user, partner_id="desk", source="onboarding", consent=True)
    assert user not in clicked["link"]
    assert "user_id" not in clicked["link"]
    assert clicked["status"] == "clicked"
    opened = apply_broker_event(code=clicked["code"], status="account_opened")
    assert opened["discount"] is None
    funded = apply_broker_event(code=clicked["code"], status="funded")
    assert funded["discount"]["pct"] == "0.15"
    assert funded["discount"]["months"] == 2
    handoff = subscription_handoff(user)
    assert handoff["discount"]["pct"] == "0.15"
    assert handoff["subscription"] == "нет данных"
    report = reconcile(
        [
            {"code": clicked["code"], "status": "funded", "reward": ""},
            {"code": "missing", "status": "funded", "reward": ""},
        ]
    )
    assert report["discrepancies"][0]["note"] == "нет перехода"
    assert "user-25-secret" not in report["csv"]
    assert "user_id" not in report["csv"]
    assert "нет данных" in report["csv"]
    with pytest.raises(ValueError, match="illegal"):
        apply_broker_event(code=clicked["code"], status="clicked")
