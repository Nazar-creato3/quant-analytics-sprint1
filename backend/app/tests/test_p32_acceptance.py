"""Prompt 32: acceptance gates from v1.1 and the v1.2 expansion."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.beta_admin.service import (
    create_invite,
    list_users,
    register_actor_for_tests,
    reset_beta_admin,
    toggle_flag,
)
from app.services.experiments.service import reset_experiments, status
from app.services.forecast_log.store import get_store
from app.services.product_analytics.metrics import metrics
from app.services.product_analytics.service import (
    plan,
    record_event,
    reset_analytics,
    stored_events,
)
from app.services.public_accuracy.service import public_accuracy
from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.subject_rights.service import (
    delete_account,
    export_account,
    hold_for_tests,
    reset_subject_rights,
    scan,
)
from app.services.subscription_billing.service import quote
from app.services.support_desk.service import (
    report,
    reset_support,
    slack_notice,
    tickets,
)
from app.services.waitlist.service import join, public_status
from app.services.waitlist.service import reset as reset_waitlist

REPO = Path(__file__).resolve().parents[3]
EMAIL = "ada@example.test"
NAME = "AdaPerson"
TOKEN = "broker-token-32"


def setup_function() -> None:
    reset_for_tests()
    reset_subject_rights()
    reset_support()
    reset_analytics()
    reset_experiments()
    reset_beta_admin()
    reset_waitlist()
    get_store().reset()


def teardown_function() -> None:
    reset_for_tests()
    reset_subject_rights()
    reset_support()
    reset_analytics()
    reset_experiments()
    reset_beta_admin()
    reset_waitlist()
    get_store().reset()


def test_v12_gates_and_acceptance_record() -> None:
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_partners") is False
    assert is_enabled("qa_partner_ads") is False
    assert is_enabled("qa_preorder") is False
    assert is_enabled("qa_experiments") is False
    assert status()["status"] == "off"
    assert public_accuracy()["accuracy"] == "нет данных"
    assert metrics()["activation"] == "нет данных"
    assert quote(user_id="p32", plan="personal", period="month")["amount"] == "10000"
    assert export_account("missing")["deadline"] == "нет данных"
    joined = join(
        email=EMAIL,
        name=NAME,
        broker="moex",
        portfolio_range="x",
        consent=True,
        honeypot="",
    )
    assert joined["status"] == "rejected"
    assert EMAIL not in json.dumps(public_status())
    assert record_event(
        name="registration",
        side="server",
        subject="user-32",
        properties={},
        consent=True,
        do_not_track=False,
    )["reason"] == "consent"
    assert stored_events() == []
    assert len(plan()) == 16
    register_actor_for_tests(actor_id="reader", role="analyst", mfa=True)
    register_actor_for_tests(actor_id="owner", role="founder", mfa=True)
    assert list_users("reader")["reason"] == "role"
    assert create_invite("owner")["reason"] == "нет данных"
    assert toggle_flag("owner", "qa_act_live", True, confirm=True, confirm_again=True)["reason"] == "нет данных"
    assert is_enabled("qa_act_live") is False
    hold_for_tests(user_id="user-32", email=EMAIL, name=NAME, token=TOKEN, consent="yes")
    delete_account("user-32")
    assert scan(EMAIL) == []
    assert scan(NAME) == []
    assert scan(TOKEN) == []
    rejected = report(
        page="/support",
        version="local",
        request_id="req-32",
        errors=[],
        description=EMAIL,
        screenshot_consent=True,
        screenshot="raw-image",
    )
    assert rejected["reason"] == "нет данных"
    assert tickets() == []
    assert slack_notice()["status"] == "нет данных"
    text = (REPO / "docs/qa/FINAL_ACCEPTANCE.md").read_text(encoding="utf-8")
    for phrase in (
        "Браузерные сценарии а–к: не выполнено.",
        "Развёртывание и откат: не выполнено.",
        "E-7Т: не закрыт.",
        "E-7M: не закрыт.",
        "E-9П: не закрыт.",
        "E-9А: не закрыт.",
        "E-9О: не закрыт.",
        "Лист ожидания не сохраняет адрес",
    ):
        assert phrase in text
    assert not (REPO / "docs/qa/audits/E-7M.md").exists()
    assert not (REPO / "docs/qa/audits/E-9P.md").exists()
