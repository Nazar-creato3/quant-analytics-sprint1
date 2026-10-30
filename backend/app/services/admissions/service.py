"""Admissions CRM service (Prompt 57) + Bitrix manual CSV export."""
from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.domain.admissions import (
    AdmissionCaseCreate,
    AdmissionCaseORM,
    AdmissionCaseRead,
    AdmissionStatus,
    AdmissionStatusHistoryORM,
    AdmissionTransitionError,
    assert_admission_transition,
    display_bucket_for_status,
)
from app.services.access_policy.service import access_policy_service
from app.utils.audit import AuditAction, audit
from app.utils.helpers import new_uuid, utcnow


BITRIX_CSV_FIELDS = [
    "TITLE",
    "NAME",
    "EMAIL",
    "PHONE",
    "SOURCE",
    "STATUS",
    "JURISDICTION",
    "CAPITAL_RANGE",
    "EXPERIENCE",
    "STRATEGY",
    "OWNER_ID",
    "NOTES",
    "CASE_ID",
    "CREATED_AT",
]


class AdmissionsService:
    async def create_lead(
        self,
        db: AsyncSession,
        body: AdmissionCaseCreate,
        *,
        actor_user_id: str | None = None,
    ) -> AdmissionCaseORM:
        case = AdmissionCaseORM(
            id=new_uuid(),
            status=AdmissionStatus.LEAD.value,
            source=body.source,
            jurisdiction=body.jurisdiction,
            capital_range=body.capital_range,
            experience_level=body.experience_level,
            strategy_interest=body.strategy_interest,
            contact_email=body.contact_email.strip().lower(),
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            user_id=body.user_id,
            notes=body.notes,
        )
        db.add(case)
        await db.flush()
        await self._append_history(
            db, case.id, None, AdmissionStatus.LEAD, actor_user_id, "create_lead"
        )
        await audit.log(
            db,
            action=getattr(AuditAction, "ADMISSION_CREATE", "admission_create"),
            user_id=actor_user_id,
            resource_type="admission_case",
            resource_id=case.id,
            details={"email": case.contact_email},
        )
        return case

    async def find_latest_case_by_email(
        self, db: AsyncSession, email: str
    ) -> AdmissionCaseORM | None:
        normalized = email.strip().lower()
        result = await db.execute(
            select(AdmissionCaseORM)
            .where(AdmissionCaseORM.contact_email == normalized)
            .order_by(AdmissionCaseORM.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def attach_user_to_case(
        self,
        db: AsyncSession,
        case: AdmissionCaseORM,
        user_id: str,
        *,
        note: str | None = None,
    ) -> AdmissionCaseORM:
        case.user_id = user_id
        if note:
            prefix = (case.notes or "").strip()
            case.notes = f"{prefix}\n{note}".strip() if prefix else note
        case.updated_at = utcnow()
        await db.flush()
        return case

    async def list_cases(self, db: AsyncSession) -> list[AdmissionCaseORM]:
        result = await db.execute(
            select(AdmissionCaseORM).order_by(AdmissionCaseORM.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_cases_paginated(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        bucket: str | None = None,
        sort: str = "created_at_desc",
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[AdmissionCaseORM], int]:
        query = select(AdmissionCaseORM)
        if status:
            query = query.where(AdmissionCaseORM.status == status)
        if bucket:
            from app.domain.admissions import DISPLAY_BUCKETS

            values = DISPLAY_BUCKETS.get(bucket)
            if values:
                query = query.where(AdmissionCaseORM.status.in_(values))

        sort_map = {
            "created_at_desc": AdmissionCaseORM.created_at.desc(),
            "created_at_asc": AdmissionCaseORM.created_at.asc(),
            "updated_at_desc": AdmissionCaseORM.updated_at.desc(),
            "email_asc": AdmissionCaseORM.contact_email.asc(),
            "email_desc": AdmissionCaseORM.contact_email.desc(),
            "status_asc": AdmissionCaseORM.status.asc(),
        }
        query = query.order_by(sort_map.get(sort, AdmissionCaseORM.created_at.desc()))

        count_result = await db.execute(select(func.count()).select_from(query.subquery()))
        total = int(count_result.scalar_one())

        offset = max(0, (page - 1) * page_size)
        result = await db.execute(query.offset(offset).limit(page_size))
        return list(result.scalars().all()), total

    async def seed_demo_cases(self, db: AsyncSession, *, count: int = 30) -> int:
        """Create demo admission leads for pagination testing (dev only)."""
        from app.domain.admissions import AdmissionStatus

        demo_statuses = [
            AdmissionStatus.LEAD,
            AdmissionStatus.TRIAL,
            AdmissionStatus.CONTACTED,
            AdmissionStatus.QUALIFIED,
            AdmissionStatus.APPROVED,
            AdmissionStatus.REJECTED,
        ]
        created = 0
        for i in range(count):
            status = demo_statuses[i % len(demo_statuses)].value
            email = f"demo-lead-{i + 1:03d}@pagination.test"
            existing = await self.find_latest_case_by_email(db, email)
            if existing:
                continue
            case = AdmissionCaseORM(
                id=new_uuid(),
                status=status,
                source="demo_seed",
                capital_range=["10-50k", "50-100k", "100-250k", "250k+"][i % 4],
                contact_email=email,
                contact_name=f"Demo Lead {i + 1}",
                notes="Auto-seeded for admissions table pagination demo",
            )
            db.add(case)
            created += 1
        if created:
            await db.flush()
        return created

    async def get_case(self, db: AsyncSession, case_id: str) -> AdmissionCaseORM | None:
        result = await db.execute(
            select(AdmissionCaseORM).where(AdmissionCaseORM.id == case_id)
        )
        return result.scalar_one_or_none()

    async def change_status(
        self,
        db: AsyncSession,
        case_id: str,
        target: AdmissionStatus,
        *,
        actor_user_id: str | None = None,
        reason: str | None = None,
        admin_override: bool = False,
    ) -> AdmissionCaseORM:
        case = await self.get_case(db, case_id)
        if not case:
            raise LookupError("Admission case not found")
        current = AdmissionStatus(case.status)
        assert_admission_transition(current, target, admin_override=admin_override)
        case.status = target.value
        case.updated_at = utcnow()
        await self._append_history(db, case.id, current, target, actor_user_id, reason)
        if target == AdmissionStatus.APPROVED:
            await self._provision_login_for_case(db, case)
        await db.flush()
        return case

    async def _provision_login_for_case(self, db: AsyncSession, case: AdmissionCaseORM) -> str | None:
        from app.services.auth.invite import provision_whitelisted_login

        user, plaintext = await provision_whitelisted_login(db, case.contact_email)
        case.user_id = user.id
        extra = dict(case.extra or {})
        extra["credentials_issued"] = True
        extra["has_platform_account"] = True
        case.extra = extra
        return plaintext

    async def invite_and_approve(
        self,
        db: AsyncSession,
        *,
        email: str,
        contact_name: str | None = None,
        actor_user_id: str | None = None,
    ) -> tuple[AdmissionCaseORM, str | None, bool]:
        """Create/whitelist a login and mark the admission case approved."""
        from app.services.auth.invite import provision_whitelisted_login

        user, plaintext = await provision_whitelisted_login(db, email)
        existing = plaintext is None
        case = await self.find_latest_case_by_email(db, email)
        if not case:
            case = await self.create_lead(
                db,
                AdmissionCaseCreate(
                    contact_email=email,
                    contact_name=contact_name,
                    source="admin_invite",
                ),
                actor_user_id=actor_user_id,
            )
        await self.attach_user_to_case(db, case, user.id, note="Platform login issued by admin")
        if AdmissionStatus(case.status) != AdmissionStatus.APPROVED:
            case = await self.change_status(
                db,
                case.id,
                AdmissionStatus.APPROVED,
                actor_user_id=actor_user_id,
                reason="admin_invite",
                admin_override=True,
            )
        else:
            await self._provision_login_for_case(db, case)
        return case, plaintext, existing

    async def start_trial(
        self,
        db: AsyncSession,
        case_id: str,
        *,
        actor_user_id: str | None = None,
        abuse_risk_score: float = 0.0,
        duplicate=None,
    ) -> tuple[AdmissionCaseORM, dict[str, Any]]:
        case = await self.get_case(db, case_id)
        if not case:
            raise LookupError("Admission case not found")
        await self.change_status(
            db, case_id, AdmissionStatus.TRIAL, actor_user_id=actor_user_id, reason="start_trial"
        )
        eligibility_meta: dict[str, Any] = {"eligible": True}
        if case.user_id:
            _row, eligibility = await access_policy_service.start_trial(
                db,
                case.user_id,
                duplicate=duplicate,
                abuse_risk_score=abuse_risk_score,
            )
            eligibility_meta = eligibility.model_dump()
            if not eligibility.eligible:
                case.extra = {**(case.extra or {}), "trial_blocked": eligibility_meta}
        return case, eligibility_meta

    async def assign_owner(
        self, db: AsyncSession, case_id: str, owner_user_id: str, *, actor_user_id: str | None = None
    ) -> AdmissionCaseORM:
        case = await self.get_case(db, case_id)
        if not case:
            raise LookupError("Admission case not found")
        case.owner_user_id = owner_user_id
        case.updated_at = utcnow()
        await db.flush()
        await audit.log(
            db,
            action="admission_assign_owner",
            user_id=actor_user_id,
            resource_type="admission_case",
            resource_id=case.id,
            details={"owner_user_id": owner_user_id},
        )
        return case

    async def add_call_note(
        self, db: AsyncSession, case_id: str, note: str, *, actor_user_id: str | None = None
    ) -> AdmissionCaseORM:
        case = await self.get_case(db, case_id)
        if not case:
            raise LookupError("Admission case not found")
        stamp = utcnow().isoformat()
        prev = case.notes or ""
        case.notes = f"{prev}\n[{stamp}] {note}".strip()
        case.updated_at = utcnow()
        await db.flush()
        await audit.log(
            db,
            action="admission_call_note",
            user_id=actor_user_id,
            resource_type="admission_case",
            resource_id=case.id,
            details={"note_len": len(note)},
        )
        return case

    async def grant_full_access(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        external_ref: str | None = None,
    ) -> None:
        """Leave trial: paper trading, then approved live. Does not skip the ladder."""
        from app.domain.access_policy import AccessLevel
        from app.services.subscription.paywall import paywall_subscription_service

        policy = await access_policy_service.read(db, user_id)
        if policy.access_level == AccessLevel.TRIAL_READ_ONLY:
            await access_policy_service.set_level(
                db, user_id, AccessLevel.PAPER_TRADING, approved=True
            )
            policy = await access_policy_service.read(db, user_id)
        if policy.access_level == AccessLevel.PAPER_TRADING:
            await access_policy_service.set_level(
                db, user_id, AccessLevel.APPROVED_LIVE, approved=True
            )
        await paywall_subscription_service.mark_paid(
            db, user_id, external_ref=external_ref or "admissions_full_access"
        )

    async def approve_account(
        self, db: AsyncSession, case_id: str, *, actor_user_id: str | None = None
    ) -> AdmissionCaseORM:
        case = await self.change_status(
            db,
            case_id,
            AdmissionStatus.APPROVED,
            actor_user_id=actor_user_id,
            reason="full_access",
            admin_override=True,
        )
        if case.user_id:
            user = await db.get(User, case.user_id)
            if user:
                user.is_whitelisted = True
                user.is_active = True
            await self.grant_full_access(db, case.user_id)
        return case

    async def reject_account(
        self, db: AsyncSession, case_id: str, reason: str, *, actor_user_id: str | None = None
    ) -> AdmissionCaseORM:
        if not reason or len(reason.strip()) < 3:
            raise ValueError("Reject reason is required")
        return await self.change_status(
            db,
            case_id,
            AdmissionStatus.REJECTED,
            actor_user_id=actor_user_id,
            reason=reason.strip(),
        )

    async def _linked_user(self, db: AsyncSession, case: AdmissionCaseORM) -> User | None:
        if case.user_id:
            user = await db.get(User, case.user_id)
            if user:
                return user
        result = await db.execute(
            select(User).where(User.email == case.contact_email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def _sync_identity_role(self, db: AsyncSession, email: str, *, admin: bool) -> None:
        from app.core.rbac_deps import get_identity_for_email
        from app.domain.rbac import SystemRole, TrustLevel

        identity = await get_identity_for_email(db, email)
        if identity is None:
            return
        if admin:
            identity.system_role = SystemRole.OWNER_ADMIN.value
            identity.trust_level = TrustLevel.PRIVILEGED.value
        else:
            identity.system_role = SystemRole.USER.value
            identity.trust_level = TrustLevel.STANDARD.value

    async def grant_admin(
        self, db: AsyncSession, case_id: str, *, actor_user_id: str | None = None
    ) -> AdmissionCaseORM:
        from app.db.models import UserRole

        case = await self.approve_account(db, case_id, actor_user_id=actor_user_id)
        user = await self._linked_user(db, case)
        if user is None:
            await self._provision_login_for_case(db, case)
            user = await self._linked_user(db, case)
        if user is None:
            raise LookupError("No platform account for this admission case")
        user.role = UserRole.ADMIN
        user.is_whitelisted = True
        user.is_active = True
        case.user_id = user.id
        await self._sync_identity_role(db, user.email, admin=True)
        extra = dict(case.extra or {})
        extra["admin_granted"] = True
        case.extra = extra
        case.updated_at = utcnow()
        await db.flush()
        await audit.log(
            db,
            action="admission_grant_admin",
            user_id=actor_user_id,
            resource_type="admission_case",
            resource_id=case.id,
            details={"user_id": user.id},
        )
        return case

    async def revoke_admin(
        self, db: AsyncSession, case_id: str, *, actor_user_id: str | None = None
    ) -> AdmissionCaseORM:
        """Remove admin role only; keep membership / full-access status as-is."""
        from app.db.models import UserRole

        case = await self.get_case(db, case_id)
        if not case:
            raise LookupError("Admission case not found")
        user = await self._linked_user(db, case)
        if user is None:
            raise LookupError("No platform account for this admission case")
        if user.role != UserRole.ADMIN:
            raise ValueError("User is not an admin")
        user.role = UserRole.VIEWER
        await self._sync_identity_role(db, user.email, admin=False)
        case.user_id = user.id
        extra = dict(case.extra or {})
        extra["admin_granted"] = False
        case.extra = extra
        case.updated_at = utcnow()
        await db.flush()
        await audit.log(
            db,
            action="admission_revoke_admin",
            user_id=actor_user_id,
            resource_type="admission_case",
            resource_id=case.id,
            details={"user_id": user.id},
        )
        return case

    async def suspend_full_access(
        self, db: AsyncSession, case_id: str, *, actor_user_id: str | None = None
    ) -> AdmissionCaseORM:
        from app.db.models import UserRole
        from app.domain.access_policy import AccessLevel

        case = await self.change_status(
            db,
            case_id,
            AdmissionStatus.SUSPENDED,
            actor_user_id=actor_user_id,
            reason="suspend_full_access",
            admin_override=True,
        )
        user = await self._linked_user(db, case)
        if user is not None:
            user.is_whitelisted = False
            if user.role == UserRole.ADMIN:
                user.role = UserRole.VIEWER
            await self._sync_identity_role(db, user.email, admin=False)
            await access_policy_service.set_level(
                db,
                user.id,
                AccessLevel.TRIAL_READ_ONLY,
                approved=True,
                reason="suspend_full_access",
            )
        extra = dict(case.extra or {})
        extra["access_limited"] = True
        case.extra = extra
        await db.flush()
        await audit.log(
            db,
            action="admission_suspend_full_access",
            user_id=actor_user_id,
            resource_type="admission_case",
            resource_id=case.id,
            details={"user_id": user.id if user else None},
        )
        return case

    async def escalate_case(
        self, db: AsyncSession, case_id: str, *, actor_user_id: str | None = None
    ) -> AdmissionCaseORM:
        case = await self.get_case(db, case_id)
        if not case:
            raise LookupError("Admission case not found")
        current = AdmissionStatus(case.status)
        target_map = {
            AdmissionStatus.LEAD: AdmissionStatus.CONTACTED,
            AdmissionStatus.TRIAL: AdmissionStatus.CONTACTED,
            AdmissionStatus.CONTACTED: AdmissionStatus.QUALIFIED,
            AdmissionStatus.QUALIFIED: AdmissionStatus.APPROVED,
        }
        target = target_map.get(current)
        if target is None:
            raise AdmissionTransitionError(
                f"Cannot escalate case in status {current.value}"
            )
        case = await self.change_status(
            db,
            case_id,
            target,
            actor_user_id=actor_user_id,
            reason="escalated",
        )
        extra = dict(case.extra or {})
        extra["escalated"] = True
        extra["escalated_at"] = utcnow().isoformat()
        case.extra = extra
        await db.flush()
        await audit.log(
            db,
            action="admission_escalated",
            user_id=actor_user_id,
            resource_type="admission_case",
            resource_id=case.id,
            details={"from_status": current.value, "to_status": target.value},
        )
        return case

    def case_to_bitrix_row(self, case: AdmissionCaseORM) -> dict[str, str]:
        return {
            "TITLE": f"Apex lead {case.contact_name or case.contact_email}",
            "NAME": case.contact_name or "",
            "EMAIL": case.contact_email or "",
            "PHONE": case.contact_phone or "",
            "SOURCE": case.source or "",
            "STATUS": case.status or "",
            "JURISDICTION": case.jurisdiction or "",
            "CAPITAL_RANGE": case.capital_range or "",
            "EXPERIENCE": case.experience_level or "",
            "STRATEGY": case.strategy_interest or "",
            "OWNER_ID": case.owner_user_id or "",
            "NOTES": (case.notes or "").replace("\n", " | ")[:2000],
            "CASE_ID": case.id,
            "CREATED_AT": case.created_at.isoformat() if case.created_at else "",
        }

    def export_bitrix_csv(self, cases: list[AdmissionCaseORM]) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=BITRIX_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for case in cases:
            writer.writerow(self.case_to_bitrix_row(case))
        return buf.getvalue()

    def to_read(self, case: AdmissionCaseORM) -> AdmissionCaseRead:
        extra = case.extra if isinstance(case.extra, dict) else {}
        trial_flag = bool(extra.get("trial_used"))
        return AdmissionCaseRead.model_validate(
            {
                **AdmissionCaseRead.model_validate(case).model_dump(),
                "trial_used": trial_flag or case.status == AdmissionStatus.TRIAL.value,
                "has_platform_account": bool(case.user_id),
                "display_bucket": display_bucket_for_status(case.status),
            }
        )

    async def to_read_enriched(
        self, db: AsyncSession, case: AdmissionCaseORM
    ) -> AdmissionCaseRead:
        read = self.to_read(case)
        trial_used = read.trial_used
        has_account = read.has_platform_account

        user = None
        uid = case.user_id
        if uid:
            user = await db.get(User, uid)
            has_account = user is not None
        else:
            user_r = await db.execute(
                select(User).where(User.email == case.contact_email.strip().lower())
            )
            user = user_r.scalar_one_or_none()
            uid = user.id if user else None
            has_account = uid is not None

        if uid:
            policy = await access_policy_service.read(db, uid)
            if policy.trial_started_at is not None:
                trial_used = True
            if policy.access_level.value in ("expired", "trial_read_only", "paper_trading"):
                trial_used = trial_used or policy.trial_started_at is not None

        admin = False
        if user is not None:
            role = user.role.value if hasattr(user.role, "value") else str(user.role)
            admin = role == "admin"
        return read.model_copy(
            update={
                "trial_used": trial_used,
                "has_platform_account": has_account,
                "is_admin": admin,
                "display_bucket": display_bucket_for_status(case.status),
            }
        )

    async def _append_history(
        self,
        db: AsyncSession,
        case_id: str,
        from_status: AdmissionStatus | None,
        to_status: AdmissionStatus,
        actor_user_id: str | None,
        reason: str | None,
    ) -> None:
        db.add(
            AdmissionStatusHistoryORM(
                id=new_uuid(),
                case_id=case_id,
                from_status=from_status.value if from_status else None,
                to_status=to_status.value,
                actor_user_id=actor_user_id,
                reason=reason,
            )
        )


admissions_service = AdmissionsService()
