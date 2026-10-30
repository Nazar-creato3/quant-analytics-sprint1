"""Prompt 28: privacy export/erase, key-access allow-list, isolation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.act_desk.service import journal_for, reset as reset_act, save_profile
from app.services.privacy.service import (
    anonymize_for_external_llm,
    erase_user_local,
    export_user_bundle,
    reset_privacy_state,
)
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.trading_keys.key_access import (
    KeyAccessDenied,
    assert_purpose,
    record_access,
    reset_access_log,
)
from app.services.trading_keys.service import excess_rights_alert, recheck_permissions


def setup_function() -> None:
    reset_for_tests()
    reset_act()
    reset_privacy_state()
    reset_access_log()


def teardown_function() -> None:
    reset_act()
    reset_privacy_state()
    reset_access_log()
    reset_for_tests()


def test_export_has_no_secrets_and_is_scoped():
    save_profile(
        "alice",
        {
            "horizon": "3y",
            "risk_tolerance": "moderate",
            "max_position_pct": "0.1",
            "max_crisis_loss_pct": "0.15",
        },
    )
    save_profile(
        "bob",
        {
            "horizon": "1y",
            "risk_tolerance": "low",
            "max_position_pct": "0.05",
            "max_crisis_loss_pct": "0.1",
        },
    )
    bundle = export_user_bundle("alice")
    assert bundle["secrets_included"] is False
    assert bundle["profile"]["user_id"] == "alice"
    assert "api_secret" not in str(bundle).lower()
    assert all(row.get("user_id") != "bob" for row in journal_for("alice"))
    bob_names = [row.get("name") for row in journal_for("bob")]
    assert "profile.saved" in bob_names


def test_erase_drops_only_that_user():
    save_profile(
        "alice",
        {
            "horizon": "3y",
            "risk_tolerance": "moderate",
            "max_position_pct": "0.1",
            "max_crisis_loss_pct": "0.15",
        },
    )
    save_profile(
        "bob",
        {
            "horizon": "1y",
            "risk_tolerance": "low",
            "max_position_pct": "0.05",
            "max_crisis_loss_pct": "0.1",
        },
    )
    out = erase_user_local("alice")
    assert out["erased"] is True
    assert journal_for("alice") == []
    assert journal_for("bob")


def test_anonymize_strips_email_and_keys():
    raw = "user n@x.io token=abc123 api_key: supersecret"
    clean = anonymize_for_external_llm(raw)
    assert "n@x.io" not in clean
    assert "supersecret" not in clean
    assert "[redacted-email]" in clean


def test_key_access_denies_ui_purpose():
    with pytest.raises(KeyAccessDenied):
        assert_purpose("ui")
    record_access(user_id="u1", key_id="k1", purpose="execution")
    with pytest.raises(KeyAccessDenied):
        record_access(user_id="u1", key_id="k1", purpose="dashboard")


def test_excess_withdraw_rights_alert():
    assert excess_rights_alert(withdraw_allowed=True, permission_warning=None)
    assert excess_rights_alert(withdraw_allowed=False, permission_warning=None) is None
    assert callable(recheck_permissions)


def test_privacy_api_and_flag_off():
    client = TestClient(app)
    assert client.get("/api/v1/privacy/data-map").status_code in (401, 403)
    from app.tests.qa_session import bind_session_user, clear_session_user

    bind_session_user("demo")
    mapped = client.get("/api/v1/privacy/data-map")
    assert mapped.status_code == 200
    assert "external_llm" not in mapped.json()
    blob = str(mapped.json()).lower()
    assert "totp" not in blob
    assert "trading_key" not in blob
    assert "qa_explanations" not in blob
    assert "users +" not in blob
    exported = client.get("/api/v1/privacy/export")
    assert exported.status_code == 200
    assert exported.json()["secrets_included"] is False
    export_blob = str(exported.json()).lower()
    assert "trading_key" not in export_blob
    assert "totp" not in export_blob
    set_global("qa_privacy", False)
    assert client.get("/api/v1/privacy/data-map").status_code == 404
    clear_session_user()
