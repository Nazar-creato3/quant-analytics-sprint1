"""Prompt 53: roles, a required second factor, and no live switch."""
from __future__ import annotations

import json
from pathlib import Path

from app.api.v1.endpoints.beta_admin import post_beta_users
from app.services.beta_admin.service import (
    add_user_for_tests,
    admin_log,
    analyst_snapshot,
    block_user,
    create_invite,
    known_roles,
    list_users,
    register_actor_for_tests,
    reset_beta_admin,
    set_seat_limit_for_tests,
    system_state,
    toggle_flag,
)
from app.services.forecast_log.store import get_store
from app.services.product_analytics.metrics import metrics
from app.services.product_analytics.service import reset_analytics
from app.services.public_accuracy.service import public_accuracy
from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.subscription_billing.service import quote

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
REPO = Path(__file__).resolve().parents[3]


def setup_function() -> None:
    reset_for_tests()
    reset_beta_admin()
    reset_analytics()
    get_store().reset()


def teardown_function() -> None:
    reset_for_tests()
    reset_beta_admin()
    reset_analytics()
    get_store().reset()


def _actor(actor_id: str, role: str, *, mfa: bool = True) -> None:
    register_actor_for_tests(actor_id=actor_id, role=role, mfa=mfa)


def test_roles_mfa_and_locked_flags() -> None:
    assert is_enabled("qa_beta_admin") is True
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_partners") is False
    assert is_enabled("qa_partner_ads") is False
    assert is_enabled("qa_preorder") is False
    assert known_roles() == ["analyst", "founder", "support"]
    assert public_accuracy()["accuracy"] == "нет данных"
    assert metrics()["activation"] == "нет данных"
    assert quote(user_id="p53", plan="personal", period="month")["amount"] == "10000"
    _actor("plain", "founder", mfa=False)
    assert list_users("plain")["reason"] == "mfa"
    _actor("reader", "analyst")
    _actor("helper", "support")
    _actor("owner", "founder")
    add_user_for_tests(user_id="u1", status="active")
    assert list_users("reader")["reason"] == "role"
    listed = list_users("helper")
    assert listed["users"] == [{"id": "u1", "status": "active"}]
    assert "token" not in json.dumps(listed)
    assert block_user("reader", "u1")["reason"] == "role"
    assert block_user("helper", "u1")["user_status"] == "blocked"
    assert create_invite("helper")["reason"] == "нет данных"
    set_seat_limit_for_tests(1)
    code = create_invite("owner")["code"]
    assert "@" not in code
    assert create_invite("owner")["reason"] == "нет данных"
    denied = post_beta_users({"actor_id": "helper", "email": "a@b.c"})
    assert denied["reason"] == "нет данных"
    snap = analyst_snapshot("reader")
    assert snap["activation"] == "нет данных"
    assert "u1" not in json.dumps(snap)
    assert toggle_flag("helper", "qa_act_live", True, confirm=True, confirm_again=True)["reason"] == "role"
    assert toggle_flag("owner", "qa_act_live", True, confirm=True, confirm_again=False)["reason"] == "role"
    legal = toggle_flag("owner", "qa_act_live", True, confirm=True, confirm_again=True)
    assert legal["reason"] == "нет данных"
    assert is_enabled("qa_act_live") is False
    assert toggle_flag("reader", "qa_experiments", True, confirm=True, confirm_again=False)["reason"] == "role"
    assert toggle_flag("helper", "qa_experiments", True, confirm=False, confirm_again=False)["reason"] == "confirm"
    assert toggle_flag("helper", "qa_experiments", True, confirm=True, confirm_again=False)["status"] == "ok"
    assert is_enabled("qa_experiments") is True
    health = system_state("reader")
    assert health["queues"] == "нет данных"
    assert health["providers"] == "нет данных"
    assert health["quotas"] == "нет данных"
    assert health["live"] is False
    first = admin_log()[0]
    system_state("owner")
    assert admin_log()[0] == first
    blob = json.dumps(admin_log())
    assert "plain" not in blob
    assert "@" not in blob
    for rel in (
        "backend/app/services/beta_admin/service.py",
        "frontend/src/lib/beta-admin.ts",
        "docs/methodology/beta-admin.md",
    ):
        text = (REPO / rel).read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN:
            assert phrase not in text
