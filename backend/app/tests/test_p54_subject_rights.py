"""Prompt 54: deletion removes personal data and invents no legal deadline."""
from __future__ import annotations

import json
from pathlib import Path

from app.api.v1.endpoints.subject_rights import get_subject_export, post_subject_delete
from app.services.beta_admin.service import list_users, reset_beta_admin
from app.services.forecast_log.store import get_store
from app.services.product_analytics.metrics import metrics
from app.services.product_analytics.service import reset_analytics, stored_events
from app.services.public_accuracy.service import public_accuracy
from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.subject_rights.service import (
    delete_account,
    disconnect_token,
    export_account,
    hold_for_tests,
    reset_subject_rights,
    revoke_consent,
    scan,
)
from app.services.subscription_billing.service import quote

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
REPO = Path(__file__).resolve().parents[3]
EMAIL = "ada@example.test"
NAME = "AdaPerson"
TOKEN = "broker-token-54"


def setup_function() -> None:
    reset_for_tests()
    reset_subject_rights()
    reset_beta_admin()
    reset_analytics()
    get_store().reset()


def teardown_function() -> None:
    reset_for_tests()
    reset_subject_rights()
    reset_beta_admin()
    reset_analytics()
    get_store().reset()


def test_deletion_scan_finds_no_personal_data() -> None:
    assert is_enabled("qa_subject_rights") is True
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_experiments") is False
    assert is_enabled("qa_preorder") is False
    assert is_enabled("qa_partners") is False
    assert list_users("nobody")["reason"] == "mfa"
    assert public_accuracy()["accuracy"] == "нет данных"
    assert metrics()["activation"] == "нет данных"
    assert quote(user_id="p54", plan="personal", period="month")["amount"] == "10000"
    hold_for_tests(user_id="user-54", email=EMAIL, name=NAME, token=TOKEN, consent="yes")
    hold_for_tests(user_id="user-other", email="other@example.test", name="OtherPerson", token="other-token", consent="yes")
    exported = export_account("user-54")
    assert exported["format"] == "json"
    assert exported["email"] == EMAIL
    assert exported["deadline"] == "нет данных"
    assert json.loads(json.dumps(exported))["name"] == NAME
    assert post_subject_delete({"user_id": "user-54", "email": EMAIL})["reason"] == "нет данных"
    assert scan(EMAIL)
    revoked = revoke_consent("user-54")
    assert revoked["consent"] == "revoked"
    removed = disconnect_token("user-54")
    assert removed["token"] == "removed"
    assert removed["broker_instruction"] == "нет данных"
    assert scan(TOKEN) == []
    result = delete_account("user-54")
    assert stored_events() == []
    assert result["deadline"] == "нет данных"
    assert result["backup"] == "нет данных"
    assert result["basis"] == "нет данных"
    assert scan(EMAIL) == []
    assert scan(NAME) == []
    assert scan("user-54") == []
    assert scan("other@example.test") == ["profiles", "events", "retention"]
    hidden = get_subject_export("user-other")
    assert "email" not in hidden
    assert hidden["deadline"] == "нет данных"
    for rel in (
        "backend/app/services/subject_rights/service.py",
        "frontend/src/lib/subject-rights.ts",
        "docs/privacy/subject-rights.md",
    ):
        path = REPO / rel
        if not path.exists():
            continue  # inside the backend container only app/ is present; CI checks the full repo
        text = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN:
            assert phrase not in text
