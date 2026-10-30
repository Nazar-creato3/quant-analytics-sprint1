from __future__ import annotations

from app.services.qa import feature_flags


def test_env_and_user_override(monkeypatch):
    feature_flags.reset_for_tests()
    assert feature_flags.is_enabled("qa_shadow_mode") is False
    monkeypatch.setenv("FF_QA_SHADOW_MODE", "1")
    assert feature_flags.is_enabled("qa_shadow_mode") is True
    monkeypatch.delenv("FF_QA_SHADOW_MODE")
    feature_flags.set_user("qa_shadow_mode", True, "u1")
    assert feature_flags.is_enabled("qa_shadow_mode", user_id="u1") is True
    assert feature_flags.is_enabled("qa_shadow_mode", user_id="u2") is False
    feature_flags.set_global("qa_new_risk_path", True)
    assert feature_flags.is_enabled("qa_new_risk_path") is True
    feature_flags.reset_for_tests()


def test_ui_shell_flag_on_by_default():
    feature_flags.reset_for_tests()
    assert feature_flags.is_enabled("qa_ui_shell") is True


def test_privacy_on_live_off():
    feature_flags.reset_for_tests()
    assert feature_flags.is_enabled("qa_privacy") is True
    assert feature_flags.is_enabled("qa_act_live") is False
    assert feature_flags.is_enabled("qa_maneuvers_user_rules") is False
    assert feature_flags.is_enabled("qa_act_model_profile") is False
    assert feature_flags.is_enabled("qa_display_unlicensed") is False
    assert feature_flags.is_enabled("qa_act_desk") is True
    assert feature_flags.is_enabled("qa_investment_profile") is True
    assert feature_flags.is_enabled("qa_qualified_docs") is False
    assert feature_flags.is_enabled("qa_explanations_llm") is False


def test_ops_endpoint_refuses_legal_locked_live_flag():
    from fastapi import HTTPException

    from app.api.v1.endpoints.feature_flags import apply_ops_flag_patch
    from app.services.qa import feature_flags as flags

    flags.reset_for_tests()
    try:
        apply_ops_flag_patch("qa_act_live", True)
        raise AssertionError("locked live flag must be refused")
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "нет данных"
    assert flags.is_enabled("qa_act_live") is False
    apply_ops_flag_patch("qa_shadow_mode", True)
    assert flags.is_enabled("qa_shadow_mode") is True
    flags.reset_for_tests()


def test_endpoint_module_declares_admin_routes():
    text = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("api/v1/endpoints/feature_flags.py")
        .read_text(encoding="utf-8")
    )
    assert 'prefix="/ops/feature-flags"' in text
    assert "require_owner_admin" in text
