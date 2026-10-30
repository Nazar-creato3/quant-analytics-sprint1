"""Unit tests for AccessPolicy transitions and permission matrix (Prompt 56)."""
from __future__ import annotations

import pytest

from app.domain.access_policy import (
    AccessAction,
    AccessLevel,
    AccessLevelChangeError,
    DuplicateIdentitySignal,
    assert_transition,
    has_access_permission,
    is_allowed_transition,
    is_full_access_level,
    trial_eligibility,
)


def test_permission_matrix_trial_readonly():
    assert has_access_permission(AccessLevel.TRIAL_READ_ONLY, AccessAction.VIEW_DASHBOARD)
    assert has_access_permission(AccessLevel.TRIAL_READ_ONLY, AccessAction.USE_PAPER_MODE)
    assert has_access_permission(AccessLevel.TRIAL_READ_ONLY, AccessAction.CREATE_DEAL_INTENT_PAPER)
    assert has_access_permission(AccessLevel.TRIAL_READ_ONLY, AccessAction.MANAGE_GRID)
    assert not has_access_permission(
        AccessLevel.TRIAL_READ_ONLY, AccessAction.CREATE_DEAL_INTENT_LIVE
    )


def test_permission_matrix_approved_live_has_withdraw_stub():
    assert has_access_permission(AccessLevel.APPROVED_LIVE, AccessAction.CREATE_DEAL_INTENT_LIVE)
    assert has_access_permission(AccessLevel.APPROVED_LIVE, AccessAction.WITHDRAW_FUNDS)


def test_locked_has_no_permissions():
    assert not has_access_permission(AccessLevel.LOCKED, AccessAction.VIEW_DASHBOARD)


def test_one_step_upgrade_paper_ok():
    assert is_allowed_transition(AccessLevel.TRIAL_READ_ONLY, AccessLevel.PAPER_TRADING)


def test_cannot_skip_trial_to_managed():
    assert not is_allowed_transition(
        AccessLevel.TRIAL_READ_ONLY, AccessLevel.MANAGED_ACCOUNT, approved=True
    )
    with pytest.raises(AccessLevelChangeError):
        assert_transition(
            AccessLevel.TRIAL_READ_ONLY, AccessLevel.MANAGED_ACCOUNT, approved=True
        )


def test_approved_live_requires_approval_flag():
    assert not is_allowed_transition(AccessLevel.PAPER_TRADING, AccessLevel.APPROVED_LIVE)
    assert is_allowed_transition(
        AccessLevel.PAPER_TRADING, AccessLevel.APPROVED_LIVE, approved=True
    )


def test_downgrade_always_allowed():
    assert is_allowed_transition(AccessLevel.ENTERPRISE, AccessLevel.PAPER_TRADING)
    assert is_allowed_transition(
        AccessLevel.PAPER_TRADING, AccessLevel.EXPIRED, force_lock=True
    )


def test_trial_eligibility_duplicate_high_confidence():
    result = trial_eligibility(
        duplicate=DuplicateIdentitySignal(
            is_duplicate=True,
            matched_cluster_id="c1",
            confidence=0.9,
            matched_signals=["device"],
        )
    )
    assert result.eligible is False
    assert result.manual_review_required is True
    assert result.reason == "duplicate_identity_high_confidence"


def test_trial_eligibility_ok():
    result = trial_eligibility()
    assert result.eligible is True


def test_scheduled_pipeline_skips_trial_accounts():
    from app.services.pipeline.eligible_users import _PIPELINE_EXCLUDED_LEVELS

    assert AccessLevel.TRIAL_READ_ONLY.value in _PIPELINE_EXCLUDED_LEVELS
    assert AccessLevel.APPROVED_LIVE.value not in _PIPELINE_EXCLUDED_LEVELS


def test_full_access_hides_trial_clock():
    assert not is_full_access_level(AccessLevel.TRIAL_READ_ONLY)
    assert not is_full_access_level(AccessLevel.PAPER_TRADING)
    assert is_full_access_level(AccessLevel.APPROVED_LIVE)
    assert is_full_access_level("managed_account")
