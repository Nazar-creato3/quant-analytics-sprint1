"""Server-side subscription / trial / paywall enforcement."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.application_flow import (
    PaywallSubscriptionStatus,
    SubscriptionStatusAuditORM,
    TRIAL_DURATION_DAYS,
    UserSubscriptionStateORM,
)
from app.utils.helpers import new_uuid, utcnow


class PaywallSubscriptionService:
    async def get_or_create(self, db: AsyncSession, user_id: str) -> UserSubscriptionStateORM:
        result = await db.execute(
            select(UserSubscriptionStateORM).where(UserSubscriptionStateORM.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row:
            await self.refresh_status(db, row)
            return row
        row = UserSubscriptionStateORM(
            id=new_uuid(),
            user_id=user_id,
            subscription_status=PaywallSubscriptionStatus.NONE.value,
        )
        db.add(row)
        await db.flush()
        return row

    async def refresh_status(
        self, db: AsyncSession, row: UserSubscriptionStateORM, now: datetime | None = None
    ) -> PaywallSubscriptionStatus:
        """Check-on-request: trial_active → trial_expired."""
        now = now or datetime.now(timezone.utc)
        current = PaywallSubscriptionStatus(row.subscription_status)

        if current == PaywallSubscriptionStatus.PAID:
            return current

        if row.trial_start_at:
            expiry = row.trial_start_at + timedelta(days=TRIAL_DURATION_DAYS)
            if now >= expiry and current == PaywallSubscriptionStatus.TRIAL_ACTIVE:
                await self._transition(
                    db,
                    row,
                    PaywallSubscriptionStatus.TRIAL_EXPIRED,
                    reason="trial_period_elapsed",
                )
                return PaywallSubscriptionStatus.TRIAL_EXPIRED
            if now < expiry and current in (
                PaywallSubscriptionStatus.NONE,
                PaywallSubscriptionStatus.TRIAL_EXPIRED,
            ):
                await self._transition(
                    db,
                    row,
                    PaywallSubscriptionStatus.TRIAL_ACTIVE,
                    reason="trial_active",
                )
                return PaywallSubscriptionStatus.TRIAL_ACTIVE

        return current

    async def start_trial_on_first_login(
        self, db: AsyncSession, user_id: str
    ) -> UserSubscriptionStateORM:
        row = await self.get_or_create(db, user_id)
        if row.trial_start_at is not None:
            return row
        row.trial_start_at = utcnow()
        await self._transition(
            db,
            row,
            PaywallSubscriptionStatus.TRIAL_ACTIVE,
            reason="first_successful_login",
        )
        return row

    async def mark_paid(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        external_ref: str | None = None,
        actor_user_id: str | None = None,
    ) -> UserSubscriptionStateORM:
        row = await self.get_or_create(db, user_id)
        row.paid_at = utcnow()
        row.payment_external_ref = external_ref
        await self._transition(
            db,
            row,
            PaywallSubscriptionStatus.PAID,
            reason="payment_webhook_verified",
            actor_user_id=actor_user_id,
            meta={"external_ref": external_ref},
        )
        return row

    async def is_paid(self, db: AsyncSession, user_id: str) -> bool:
        row = await self.get_or_create(db, user_id)
        status = await self.refresh_status(db, row)
        return status == PaywallSubscriptionStatus.PAID

    async def snapshot(self, db: AsyncSession, user_id: str) -> dict:
        """Cabinet countdown + paywall state. Clock is trial_start + 48h."""
        row = await self.get_or_create(db, user_id)
        status = await self.refresh_status(db, row)
        expires_at = None
        remaining = 0
        if row.trial_start_at:
            start = row.trial_start_at
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            expires_at = start + timedelta(days=TRIAL_DURATION_DAYS)
            remaining = max(
                0, int((expires_at - datetime.now(timezone.utc)).total_seconds())
            )
        paid = status == PaywallSubscriptionStatus.PAID
        show_timer = (not paid) and status in (
            PaywallSubscriptionStatus.TRIAL_ACTIVE,
            PaywallSubscriptionStatus.TRIAL_EXPIRED,
        )
        counting = show_timer and status == PaywallSubscriptionStatus.TRIAL_ACTIVE
        return {
            "subscription_status": status.value,
            "trial_expires_at": expires_at.isoformat() if expires_at and counting else None,
            "trial_remaining_seconds": remaining if counting else 0,
            "paid": paid,
            "show_trial_timer": show_timer,
        }

    async def _transition(
        self,
        db: AsyncSession,
        row: UserSubscriptionStateORM,
        target: PaywallSubscriptionStatus,
        *,
        reason: str | None = None,
        actor_user_id: str | None = None,
        meta: dict | None = None,
    ) -> None:
        if row.subscription_status == target.value:
            return
        db.add(
            SubscriptionStatusAuditORM(
                id=new_uuid(),
                user_id=row.user_id,
                from_status=row.subscription_status,
                to_status=target.value,
                reason=reason,
                actor_user_id=actor_user_id,
                meta=meta or {},
            )
        )
        row.subscription_status = target.value
        row.updated_at = utcnow()
        await db.flush()


paywall_subscription_service = PaywallSubscriptionService()
