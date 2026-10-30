"""Prompt 26: fixture subscription. Does not import app.main."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.subscription_billing.service import (
    access_for,
    apply_fixture,
    cancel,
    charge_due,
    funnel_names,
    open_trial,
    quote,
    reset,
    sign_fixture,
    unbind_card,
)

_FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
_SECRET = "fixture-only"


def setup_function() -> None:
    reset_for_tests()
    reset()


def teardown_function() -> None:
    reset_for_tests()
    reset()


def _event(event_id: str, status: str, **kwargs):
    return apply_fixture(
        user_id="sub-user",
        event_id=event_id,
        status=status,
        signature=sign_fixture(secret=_SECRET, event_id=event_id, status=status),
        secret=_SECRET,
        **kwargs,
    )


def test_founder_price_listed_payment_flag_off():
    """Founder 08.10: 10000 RUB/month; payment stays off until subscription approved."""
    assert is_enabled("qa_partners") is False
    assert is_enabled("qa_partner_ads") is False
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_subscription_notice") is False
    assert is_enabled("qa_payment") is False
    body = quote(user_id="sub-user", plan="personal", period="month")
    assert body["amount"] == "10000"
    assert body["currency"] == "RUB"
    assert body["checkout"] == "off"
    assert body["notice"] == "нет данных"
    assert body["license"] == "нет данных"
    assert body["discount"] is None
    year = quote(user_id="sub-user", plan="personal", period="year")
    assert year["amount"] == "нет данных"
    text = (
        Path(__file__).resolve().parents[1].joinpath("services/subscription_billing/service.py").read_text(encoding="utf-8").lower()
    )
    for phrase in _FORBIDDEN:
        assert phrase not in text


def test_fixture_payment_then_cancel_and_repeat_webhook():
    opened = open_trial("sub-user")
    assert opened["access"]["mode"] == "read"
    missing = _event("e-empty", "succeeded")
    assert missing["reason"] == "нет данных"
    assert access_for("trial")["live"] is False
    paid = _event("e-pay", "succeeded", fixture_amount="1.00", consent=True, autopay=True)
    assert paid["status"] == "paid"
    assert paid["access"]["mode"] == "full"
    assert paid["access"]["live"] is False
    again = _event("e-pay", "succeeded", fixture_amount="1.00", consent=True, autopay=True)
    assert again == paid
    assert funnel_names().count("subscription.paid") == 1
    bad = apply_fixture(
        user_id="sub-user",
        event_id="e-bad",
        status="succeeded",
        signature="nope",
        secret=_SECRET,
        fixture_amount="1.00",
    )
    assert bad["reason"] == "подпись"
    with pytest.raises(ValueError, match="соглас"):
        _event("e-auto", "succeeded", fixture_amount="1.00", autopay=True, consent=False)
    failed = _event("e-fail", "canceled")
    assert failed["status"] == "paid"
    unbound = unbind_card("sub-user")
    assert unbound["autopay"] is False
    assert charge_due("sub-user")["reason"] == "карта отвязана"
    stopped = cancel("sub-user")
    assert stopped["status"] == "cancelled"
    assert stopped["access"]["mode"] == "read"
    refunded = open_trial("sub-refund")
    assert refunded["status"] == "trial"
    apply_fixture(
        user_id="sub-refund",
        event_id="e-ref-pay",
        status="succeeded",
        signature=sign_fixture(secret=_SECRET, event_id="e-ref-pay", status="succeeded"),
        secret=_SECRET,
        fixture_amount="1.00",
    )
    back = apply_fixture(
        user_id="sub-refund",
        event_id="e-ref",
        status="refund",
        signature=sign_fixture(secret=_SECRET, event_id="e-ref", status="refund"),
        secret=_SECRET,
    )
    assert back["status"] == "cancelled"
    assert back["access"]["mode"] == "read"
