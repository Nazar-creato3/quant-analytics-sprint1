"""AccessPolicy — membership access levels and permission matrix (Prompt 56)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import new_uuid, utcnow


class AccessLevel(str, Enum):
    TRIAL_READ_ONLY = "trial_read_only"
    PAPER_TRADING = "paper_trading"
    APPROVED_LIVE = "approved_live"
    RESTRICTED_LIVE = "restricted_live"
    MANAGED_ACCOUNT = "managed_account"
    ENTERPRISE = "enterprise"
    LOCKED = "locked"
    EXPIRED = "expired"


class AccessAction(str, Enum):
    VIEW_DASHBOARD = "view_dashboard"
    USE_PAPER_MODE = "use_paper_mode"
    CREATE_DEAL_INTENT_PAPER = "create_deal_intent_paper"
    CREATE_DEAL_INTENT_LIVE = "create_deal_intent_live"
    APPROVE_MANEUVER = "approve_maneuver"
    MANAGE_GRID = "manage_grid"
    VIEW_CRM = "view_crm"
    MANAGE_CRM = "manage_crm"
    WITHDRAW_FUNDS = "withdraw_funds"  # stub permission — no custody implementation
    BILLING_VIEW = "billing_view"
    BILLING_MANAGE = "billing_manage"


# Explicit ordered ladder — cannot skip levels without approval path.
ACCESS_LEVEL_LADDER: list[AccessLevel] = [
    AccessLevel.TRIAL_READ_ONLY,
    AccessLevel.PAPER_TRADING,
    AccessLevel.APPROVED_LIVE,
    AccessLevel.RESTRICTED_LIVE,
    AccessLevel.MANAGED_ACCOUNT,
    AccessLevel.ENTERPRISE,
]

PERMISSION_MATRIX: dict[AccessLevel, frozenset[AccessAction]] = {
    AccessLevel.TRIAL_READ_ONLY: frozenset(
        {
            AccessAction.VIEW_DASHBOARD,
            AccessAction.USE_PAPER_MODE,
            AccessAction.CREATE_DEAL_INTENT_PAPER,
            AccessAction.APPROVE_MANEUVER,
            AccessAction.MANAGE_GRID,
        }
    ),
    AccessLevel.PAPER_TRADING: frozenset(
        {
            AccessAction.VIEW_DASHBOARD,
            AccessAction.USE_PAPER_MODE,
            AccessAction.CREATE_DEAL_INTENT_PAPER,
            AccessAction.APPROVE_MANEUVER,
            AccessAction.MANAGE_GRID,
            AccessAction.BILLING_VIEW,
        }
    ),
    AccessLevel.APPROVED_LIVE: frozenset(
        {
            AccessAction.VIEW_DASHBOARD,
            AccessAction.USE_PAPER_MODE,
            AccessAction.CREATE_DEAL_INTENT_PAPER,
            AccessAction.CREATE_DEAL_INTENT_LIVE,
            AccessAction.APPROVE_MANEUVER,
            AccessAction.MANAGE_GRID,
            AccessAction.BILLING_VIEW,
            AccessAction.WITHDRAW_FUNDS,  # permission stub only
        }
    ),
    AccessLevel.RESTRICTED_LIVE: frozenset(
        {
            AccessAction.VIEW_DASHBOARD,
            AccessAction.USE_PAPER_MODE,
            AccessAction.CREATE_DEAL_INTENT_PAPER,
            AccessAction.CREATE_DEAL_INTENT_LIVE,
            AccessAction.APPROVE_MANEUVER,
            AccessAction.BILLING_VIEW,
        }
    ),
    AccessLevel.MANAGED_ACCOUNT: frozenset(
        {
            AccessAction.VIEW_DASHBOARD,
            AccessAction.USE_PAPER_MODE,
            AccessAction.CREATE_DEAL_INTENT_PAPER,
            AccessAction.CREATE_DEAL_INTENT_LIVE,
            AccessAction.APPROVE_MANEUVER,
            AccessAction.MANAGE_GRID,
            AccessAction.BILLING_VIEW,
            AccessAction.BILLING_MANAGE,
            AccessAction.WITHDRAW_FUNDS,
        }
    ),
    AccessLevel.ENTERPRISE: frozenset(set(AccessAction)),
    AccessLevel.LOCKED: frozenset(),
    AccessLevel.EXPIRED: frozenset({AccessAction.VIEW_DASHBOARD, AccessAction.BILLING_VIEW}),
}

# Allowed one-step (or same) upgrades without special approval; jumps require approval.
APPROVAL_REQUIRED_TARGETS = frozenset(
    {
        AccessLevel.APPROVED_LIVE,
        AccessLevel.RESTRICTED_LIVE,
        AccessLevel.MANAGED_ACCOUNT,
        AccessLevel.ENTERPRISE,
    }
)


def is_full_access_level(level: AccessLevel | str) -> bool:
    """Paid or operator-granted live/managed access — trial clock must hide."""
    try:
        parsed = level if isinstance(level, AccessLevel) else AccessLevel(level)
    except ValueError:
        return False
    return parsed in APPROVAL_REQUIRED_TARGETS


DEFAULT_TRIAL_DAYS = 2


class AccessLevelChangeError(ValueError):
    """Raised when an access-level transition is not allowed."""


def permissions_for(level: AccessLevel | str) -> frozenset[AccessAction]:
    lvl = AccessLevel(level) if not isinstance(level, AccessLevel) else level
    return PERMISSION_MATRIX.get(lvl, frozenset())


def has_access_permission(level: AccessLevel | str, action: AccessAction | str) -> bool:
    act = AccessAction(action) if not isinstance(action, AccessAction) else action
    return act in permissions_for(level)


def ladder_index(level: AccessLevel) -> int:
    if level in (AccessLevel.LOCKED, AccessLevel.EXPIRED):
        return -1
    return ACCESS_LEVEL_LADDER.index(level)


def is_allowed_transition(
    current: AccessLevel,
    target: AccessLevel,
    *,
    approved: bool = False,
    force_lock: bool = False,
) -> bool:
    """Return True if moving current → target is permitted."""
    if current == target:
        return True
    if force_lock and target in (AccessLevel.LOCKED, AccessLevel.EXPIRED):
        return True
    if target in (AccessLevel.LOCKED, AccessLevel.EXPIRED):
        # Downgrade / expire always allowed (system jobs).
        return True
    if current in (AccessLevel.LOCKED, AccessLevel.EXPIRED):
        # Re-open only to trial or paper with approval.
        return approved and target in (
            AccessLevel.TRIAL_READ_ONLY,
            AccessLevel.PAPER_TRADING,
        )

    cur_i = ladder_index(current)
    tgt_i = ladder_index(target)
    if tgt_i < 0:
        return False
    if tgt_i == cur_i + 1:
        # One-step up: live+ still needs approval flag.
        if target in APPROVAL_REQUIRED_TARGETS and not approved:
            return False
        return True
    if tgt_i < cur_i:
        # Downgrade always ok.
        return True
    # Skip ahead (e.g. trial → managed) — never without approval, and still not allowed
    # as a silent jump: require approved AND explicit allow_skip is handled by caller.
    if approved and tgt_i > cur_i + 1:
        return False  # cannot skip levels even with approval
    return False


def assert_transition(
    current: AccessLevel,
    target: AccessLevel,
    *,
    approved: bool = False,
    force_lock: bool = False,
) -> None:
    if not is_allowed_transition(
        current, target, approved=approved, force_lock=force_lock
    ):
        raise AccessLevelChangeError(
            f"Transition {current.value} → {target.value} is not allowed "
            f"(approved={approved})."
        )


class AccessPolicyStateORM(Base):
    """Per-user access policy state (1:1 with profiles/users)."""

    __tablename__ = "access_policy_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    access_level: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=AccessLevel.TRIAL_READ_ONLY.value,
        server_default="trial_read_only",
    )
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    manual_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    identity_cluster_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    trust_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="standard", server_default="standard"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class AccessPolicyRead(BaseModel):
    user_id: str
    access_level: AccessLevel
    permissions: list[str]
    trial_started_at: datetime | None = None
    trial_expires_at: datetime | None = None
    manual_review_required: bool = False
    identity_cluster_id: str | None = None
    trust_level: str = "standard"


class TrialEligibilityResult(BaseModel):
    eligible: bool
    reason: str
    manual_review_required: bool = False
    matched_cluster_id: str | None = None
    confidence: float = 0.0
    matched_signals: list[str] = Field(default_factory=list)


class DuplicateIdentitySignal(BaseModel):
    is_duplicate: bool
    matched_cluster_id: str | None = None
    confidence: float = 0.0
    matched_signals: list[str] = Field(default_factory=list)


def trial_eligibility(
    *,
    duplicate: DuplicateIdentitySignal | None = None,
    abuse_risk_score: float = 0.0,
    already_had_trial: bool = False,
    high_confidence_threshold: float = 0.75,
    review_risk_threshold: float = 0.45,
) -> TrialEligibilityResult:
    """Decide whether a user may start a trial (Prompt 56 + hooks for 58/65)."""
    if already_had_trial:
        return TrialEligibilityResult(
            eligible=False,
            reason="trial_already_consumed",
            manual_review_required=True,
        )
    if duplicate and duplicate.is_duplicate and duplicate.confidence >= high_confidence_threshold:
        return TrialEligibilityResult(
            eligible=False,
            reason="duplicate_identity_high_confidence",
            manual_review_required=True,
            matched_cluster_id=duplicate.matched_cluster_id,
            confidence=duplicate.confidence,
            matched_signals=list(duplicate.matched_signals),
        )
    if abuse_risk_score >= review_risk_threshold or (
        duplicate and duplicate.is_duplicate and duplicate.confidence >= review_risk_threshold
    ):
        return TrialEligibilityResult(
            eligible=False,
            reason="manual_review_required",
            manual_review_required=True,
            matched_cluster_id=duplicate.matched_cluster_id if duplicate else None,
            confidence=max(abuse_risk_score, duplicate.confidence if duplicate else 0.0),
            matched_signals=list(duplicate.matched_signals) if duplicate else [],
        )
    return TrialEligibilityResult(eligible=True, reason="ok")


def compute_trial_expiry(
    started_at: datetime | None = None,
    *,
    days: int = DEFAULT_TRIAL_DAYS,
) -> tuple[datetime, datetime]:
    start = started_at or datetime.now(timezone.utc)
    return start, start + timedelta(days=days)


def manual_review_required(
    *,
    policy_flag: bool = False,
    target_level: AccessLevel | None = None,
    eligibility: TrialEligibilityResult | None = None,
) -> bool:
    if policy_flag:
        return True
    if eligibility and eligibility.manual_review_required:
        return True
    if target_level in APPROVAL_REQUIRED_TARGETS:
        return True
    return False
