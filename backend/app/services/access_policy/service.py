"""AccessPolicy service — persist levels, transitions, trial expiry (Prompt 56)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access_policy import (
    DEFAULT_TRIAL_DAYS,
    AccessAction,
    AccessLevel,
    AccessLevelChangeError,
    AccessPolicyRead,
    AccessPolicyStateORM,
    DuplicateIdentitySignal,
    TrialEligibilityResult,
    assert_transition,
    compute_trial_expiry,
    has_access_permission,
    permissions_for,
    trial_eligibility,
)
from app.db.models import User, UserRole
from app.domain.profile import ProfileORM
from app.utils.helpers import new_uuid, utcnow


class AccessPolicyService:
    async def get_or_create(self, db: AsyncSession, user_id: str) -> AccessPolicyStateORM:
        result = await db.execute(
            select(AccessPolicyStateORM).where(AccessPolicyStateORM.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row:
            return row
        user = await db.get(User, user_id)
        default_level = AccessLevel.TRIAL_READ_ONLY
        if user and user.role in (UserRole.ADMIN, UserRole.ANALYST):
            default_level = AccessLevel.PAPER_TRADING
        start, expiry = compute_trial_expiry(days=DEFAULT_TRIAL_DAYS)
        row = AccessPolicyStateORM(
            id=new_uuid(),
            user_id=user_id,
            access_level=default_level.value,
            trial_started_at=start,
            trial_expires_at=expiry,
            manual_review_required=False,
        )
        db.add(row)
        await self._sync_profile_access_level(db, user_id, default_level)
        await db.flush()
        return row

    async def read(self, db: AsyncSession, user_id: str) -> AccessPolicyRead:
        row = await self.get_or_create(db, user_id)
        user = await db.get(User, user_id)
        if (
            user
            and user.role in (UserRole.ADMIN, UserRole.ANALYST)
            and row.access_level == AccessLevel.TRIAL_READ_ONLY.value
        ):
            row.access_level = AccessLevel.PAPER_TRADING.value
            await self._sync_profile_access_level(db, user_id, AccessLevel.PAPER_TRADING)
            await db.flush()
        level = AccessLevel(row.access_level)
        return AccessPolicyRead(
            user_id=user_id,
            access_level=level,
            permissions=[a.value for a in sorted(permissions_for(level), key=lambda x: x.value)],
            trial_started_at=row.trial_started_at,
            trial_expires_at=row.trial_expires_at,
            manual_review_required=row.manual_review_required,
            identity_cluster_id=row.identity_cluster_id,
            trust_level=row.trust_level,
        )

    async def can(self, db: AsyncSession, user_id: str, action: AccessAction | str) -> bool:
        row = await self.get_or_create(db, user_id)
        return has_access_permission(row.access_level, action)

    async def set_level(
        self,
        db: AsyncSession,
        user_id: str,
        target: AccessLevel,
        *,
        approved: bool = False,
        force_lock: bool = False,
        reason: str | None = None,
    ) -> AccessPolicyStateORM:
        row = await self.get_or_create(db, user_id)
        current = AccessLevel(row.access_level)
        assert_transition(current, target, approved=approved, force_lock=force_lock)
        row.access_level = target.value
        row.updated_at = utcnow()
        if target == AccessLevel.TRIAL_READ_ONLY and current != AccessLevel.TRIAL_READ_ONLY:
            start, expiry = compute_trial_expiry(days=DEFAULT_TRIAL_DAYS)
            row.trial_started_at = start
            row.trial_expires_at = expiry
        if target in (AccessLevel.APPROVED_LIVE, AccessLevel.PAPER_TRADING):
            row.manual_review_required = False
        if target in (
            AccessLevel.APPROVED_LIVE,
            AccessLevel.RESTRICTED_LIVE,
            AccessLevel.MANAGED_ACCOUNT,
            AccessLevel.ENTERPRISE,
        ):
            from app.services.subscription.paywall import paywall_subscription_service

            await paywall_subscription_service.mark_paid(
                db, user_id, external_ref=reason or "full_access_level"
            )
        await self._sync_profile_access_level(db, user_id, target)
        await db.flush()
        return row

    async def start_trial(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        duplicate: DuplicateIdentitySignal | None = None,
        abuse_risk_score: float = 0.0,
        already_had_trial: bool = False,
    ) -> tuple[AccessPolicyStateORM | None, TrialEligibilityResult]:
        eligibility = trial_eligibility(
            duplicate=duplicate,
            abuse_risk_score=abuse_risk_score,
            already_had_trial=already_had_trial,
        )
        row = await self.get_or_create(db, user_id)
        if not eligibility.eligible:
            row.manual_review_required = True
            if eligibility.matched_cluster_id:
                row.identity_cluster_id = eligibility.matched_cluster_id
            await db.flush()
            return None, eligibility
        start, expiry = compute_trial_expiry(days=DEFAULT_TRIAL_DAYS)
        row.access_level = AccessLevel.TRIAL_READ_ONLY.value
        row.trial_started_at = start
        row.trial_expires_at = expiry
        row.manual_review_required = False
        if duplicate and duplicate.matched_cluster_id:
            row.identity_cluster_id = duplicate.matched_cluster_id
        await self._sync_profile_access_level(db, user_id, AccessLevel.TRIAL_READ_ONLY)
        await db.flush()
        return row, eligibility

    async def expire_due_trials(self, db: AsyncSession, now: datetime | None = None) -> int:
        """Job: trial_read_only past expiry → expired. Returns count."""
        now = now or datetime.now(timezone.utc)
        result = await db.execute(
            select(AccessPolicyStateORM).where(
                AccessPolicyStateORM.access_level == AccessLevel.TRIAL_READ_ONLY.value,
                AccessPolicyStateORM.trial_expires_at.is_not(None),
                AccessPolicyStateORM.trial_expires_at <= now,
            )
        )
        rows = list(result.scalars().all())
        for row in rows:
            row.access_level = AccessLevel.EXPIRED.value
            row.updated_at = utcnow()
            await self._sync_profile_access_level(db, row.user_id, AccessLevel.EXPIRED)
        await db.flush()
        return len(rows)

    async def _sync_profile_access_level(
        self, db: AsyncSession, user_id: str, level: AccessLevel
    ) -> None:
        result = await db.execute(select(ProfileORM).where(ProfileORM.id == user_id))
        profile = result.scalar_one_or_none()
        if profile is None:
            return
        if hasattr(profile, "access_level"):
            profile.access_level = level.value


access_policy_service = AccessPolicyService()
