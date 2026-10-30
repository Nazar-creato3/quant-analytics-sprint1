"""DeviceIdentityService (Prompt 58)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access_policy import DuplicateIdentitySignal, trial_eligibility
from app.domain.device_identity import (
    ClusterMemberType,
    DeviceORM,
    IdentityClusterMemberORM,
    IdentityClusterORM,
    SessionDeviceORM,
    hash_fingerprint,
    ip_range_key,
)
from app.db.models import User
from app.domain.rbac import IdentityORM, TrustLevel, map_legacy_user_role, trust_level_for_role, is_staff_admin_role
from app.services.device_trust.policy import DevicePolicyDecision, policy_for_trust_level
from app.utils.audit import AuditAction, audit
from app.utils.helpers import new_uuid, utcnow


class DeviceIdentityService:
    async def fingerprint_device(
        self,
        db: AsyncSession,
        *,
        fingerprint_raw: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> DeviceORM:
        fp_hash = hash_fingerprint(fingerprint_raw)
        result = await db.execute(
            select(DeviceORM).where(DeviceORM.fingerprint_hash == fp_hash)
        )
        device = result.scalar_one_or_none()
        if device:
            device.last_seen_at = utcnow()
            device.last_ip = ip or device.last_ip
            if user_agent:
                device.user_agent = user_agent
            await db.flush()
            return device
        device = DeviceORM(
            id=new_uuid(),
            fingerprint_hash=fp_hash,
            user_agent=user_agent,
            last_ip=ip,
        )
        db.add(device)
        await db.flush()
        await self._ensure_cluster_for_device(db, device, ip)
        return device

    async def register_device_for_user(
        self,
        db: AsyncSession,
        user_id: str,
        device: DeviceORM,
        *,
        trust_level: TrustLevel | str = TrustLevel.STANDARD,
        is_new_binding: bool = True,
        actor_user_id: str | None = None,
        privileged_login: bool = False,
    ) -> SessionDeviceORM:
        decision = await self._evaluate_device_policy(
            db,
            user_id=user_id,
            device_id=device.id,
            trust_level=trust_level,
            is_new_account_on_device=is_new_binding,
        )
        if not decision.allowed:
            raise ValueError(decision.reason)

        link = SessionDeviceORM(id=new_uuid(), user_id=user_id, device_id=device.id)
        db.add(link)
        cluster_id = await self._cluster_id_for_device(db, device.id)
        if cluster_id:
            await self._add_member(
                db, cluster_id, ClusterMemberType.USER, user_id, confidence=1.0
            )
        await db.flush()

        await audit.log(
            db,
            action=AuditAction.DEVICE_REGISTERED,
            user_id=actor_user_id or user_id,
            resource_type="device",
            resource_id=device.id,
            details={"trust_level": str(trust_level), "policy_reason": decision.reason},
        )
        if privileged_login or TrustLevel(trust_level) == TrustLevel.PRIVILEGED:
            await audit.log(
                db,
                action="privileged_login",
                user_id=actor_user_id or user_id,
                resource_type="device",
                resource_id=device.id,
                details={"trust_level": str(trust_level)},
            )
        return link

    async def _evaluate_device_policy(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        device_id: str,
        trust_level: TrustLevel | str,
        is_new_account_on_device: bool,
    ) -> DevicePolicyDecision:
        active_devices = await self._count_user_devices(db, user_id)
        accounts_on_device = await self._count_device_accounts(db, device_id)
        return policy_for_trust_level(trust_level).evaluate(
            active_devices=active_devices,
            accounts_on_device=accounts_on_device,
            is_new_account_on_device=is_new_account_on_device,
        )

    async def resolve_trust_level(
        self, db: AsyncSession, email: str, *, default: TrustLevel = TrustLevel.STANDARD
    ) -> TrustLevel:
        result = await db.execute(select(IdentityORM).where(IdentityORM.primary_email == email))
        identity = result.scalar_one_or_none()
        if identity is not None:
            try:
                return TrustLevel(identity.trust_level)
            except ValueError:
                pass
        user_result = await db.execute(select(User).where(User.email == email))
        user = user_result.scalar_one_or_none()
        if user is not None:
            role = map_legacy_user_role(
                user.role.value if hasattr(user.role, "value") else str(user.role)
            )
            return trust_level_for_role(role)
        return default

    async def resolve_device_trust(self, db: AsyncSession, device_id: str) -> TrustLevel:
        """Privileged if any account already bound to this device is staff/privileged."""
        from app.core.config import settings

        if getattr(settings, "ALLOW_MULTI_ACCOUNT_DEVICES", False):
            count = await self._count_device_accounts(db, device_id)
            if count >= 1:
                return TrustLevel.PRIVILEGED

        result = await db.execute(
            select(User.role, IdentityORM.trust_level, IdentityORM.system_role)
            .select_from(SessionDeviceORM)
            .join(User, User.id == SessionDeviceORM.user_id)
            .outerjoin(IdentityORM, IdentityORM.user_id == User.id)
            .where(SessionDeviceORM.device_id == device_id)
        )
        for role, identity_trust, system_role in result.all():
            role_str = role.value if hasattr(role, "value") else str(role)
            mapped = map_legacy_user_role(role_str)
            if is_staff_admin_role(mapped) or trust_level_for_role(mapped) == TrustLevel.PRIVILEGED:
                return TrustLevel.PRIVILEGED
            if system_role and is_staff_admin_role(system_role):
                return TrustLevel.PRIVILEGED
            if identity_trust == TrustLevel.PRIVILEGED.value:
                return TrustLevel.PRIVILEGED
        return TrustLevel.STANDARD

    async def resolve_effective_trust(
        self,
        db: AsyncSession,
        email: str,
        *,
        device_id: str | None = None,
    ) -> TrustLevel:
        """Trust for device-binding policy — never inherit staff device privilege for other users."""
        return await self.resolve_trust_level(db, email)

    async def _count_user_devices(self, db: AsyncSession, user_id: str) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(SessionDeviceORM)
            .where(SessionDeviceORM.user_id == user_id)
        )
        return int(result.scalar_one() or 0)

    async def _count_device_accounts(self, db: AsyncSession, device_id: str) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(SessionDeviceORM)
            .where(SessionDeviceORM.device_id == device_id)
        )
        return int(result.scalar_one() or 0)

    async def detect_duplicate_identity(
        self,
        db: AsyncSession,
        *,
        fingerprint_raw: str | None = None,
        ip: str | None = None,
        payment_instrument_hash: str | None = None,
        user_id: str | None = None,
    ) -> DuplicateIdentitySignal:
        signals: list[str] = []
        cluster_ids: set[str] = set()
        confidence = 0.0

        if fingerprint_raw:
            fp_hash = hash_fingerprint(fingerprint_raw)
            device_r = await db.execute(
                select(DeviceORM).where(DeviceORM.fingerprint_hash == fp_hash)
            )
            device = device_r.scalar_one_or_none()
            if device:
                cid = await self._cluster_id_for_device(db, device.id)
                if cid and await self._cluster_has_other_users(db, cid, user_id):
                    signals.append("device")
                    cluster_ids.add(cid)
                    confidence = max(confidence, 0.85)

        ipk = ip_range_key(ip)
        if ipk:
            members = await self._members_by_key(db, ClusterMemberType.IP_RANGE, ipk)
            for m in members:
                if await self._cluster_has_other_users(db, m.cluster_id, user_id):
                    signals.append("ip_range")
                    cluster_ids.add(m.cluster_id)
                    confidence = max(confidence, 0.55)

        if payment_instrument_hash:
            members = await self._members_by_key(
                db, ClusterMemberType.PAYMENT_HASH, payment_instrument_hash
            )
            for m in members:
                signals.append("payment_instrument")
                cluster_ids.add(m.cluster_id)
                confidence = max(confidence, 0.9)

        matched = next(iter(cluster_ids), None)
        return DuplicateIdentitySignal(
            is_duplicate=bool(signals),
            matched_cluster_id=matched,
            confidence=confidence,
            matched_signals=sorted(set(signals)),
        )

    async def block_trial_abuse(
        self,
        db: AsyncSession,
        *,
        fingerprint_raw: str | None,
        ip: str | None,
        already_had_trial: bool = False,
        abuse_risk_score: float = 0.0,
    ):
        dup = await self.detect_duplicate_identity(
            db, fingerprint_raw=fingerprint_raw, ip=ip
        )
        return trial_eligibility(
            duplicate=dup,
            abuse_risk_score=abuse_risk_score,
            already_had_trial=already_had_trial,
        )

    async def admin_override_cluster(
        self, db: AsyncSession, cluster_id: str, *, comment: str, actor_user_id: str
    ) -> IdentityClusterORM:
        if not comment or len(comment.strip()) < 3:
            raise ValueError("Override comment required")
        result = await db.execute(
            select(IdentityClusterORM).where(IdentityClusterORM.id == cluster_id)
        )
        cluster = result.scalar_one_or_none()
        if not cluster:
            raise LookupError("Cluster not found")
        note = f"[override by {actor_user_id}] {comment.strip()}"
        cluster.notes = f"{cluster.notes or ''}\n{note}".strip()
        await audit.log(
            db,
            action=AuditAction.DEVICE_OVERRIDE,
            user_id=actor_user_id,
            resource_type="identity_cluster",
            resource_id=cluster_id,
            details={"comment": comment.strip()},
        )
        await db.flush()
        return cluster

    async def _ensure_cluster_for_device(
        self, db: AsyncSession, device: DeviceORM, ip: str | None
    ) -> str:
        existing = await self._cluster_id_for_device(db, device.id)
        if existing:
            return existing
        # Try merge via IP range
        ipk = ip_range_key(ip)
        if ipk:
            members = await self._members_by_key(db, ClusterMemberType.IP_RANGE, ipk)
            if members:
                cid = members[0].cluster_id
                await self._add_member(
                    db, cid, ClusterMemberType.DEVICE, device.id, confidence=0.8
                )
                return cid
        cluster = IdentityClusterORM(id=new_uuid())
        db.add(cluster)
        await db.flush()
        await self._add_member(
            db, cluster.id, ClusterMemberType.DEVICE, device.id, confidence=1.0
        )
        if ipk:
            await self._add_member(
                db, cluster.id, ClusterMemberType.IP_RANGE, ipk, confidence=0.6
            )
        return cluster.id

    async def _cluster_id_for_device(self, db: AsyncSession, device_id: str) -> str | None:
        result = await db.execute(
            select(IdentityClusterMemberORM).where(
                IdentityClusterMemberORM.member_type == ClusterMemberType.DEVICE.value,
                IdentityClusterMemberORM.member_key == device_id,
            )
        )
        row = result.scalar_one_or_none()
        return row.cluster_id if row else None

    async def _add_member(
        self,
        db: AsyncSession,
        cluster_id: str,
        member_type: ClusterMemberType,
        member_key: str,
        *,
        confidence: float,
    ) -> None:
        existing = await db.execute(
            select(IdentityClusterMemberORM).where(
                IdentityClusterMemberORM.cluster_id == cluster_id,
                IdentityClusterMemberORM.member_type == member_type.value,
                IdentityClusterMemberORM.member_key == member_key,
            )
        )
        if existing.scalar_one_or_none():
            return
        db.add(
            IdentityClusterMemberORM(
                id=new_uuid(),
                cluster_id=cluster_id,
                member_type=member_type.value,
                member_key=member_key,
                confidence=confidence,
            )
        )

    async def _members_by_key(
        self, db: AsyncSession, member_type: ClusterMemberType, key: str
    ) -> list[IdentityClusterMemberORM]:
        result = await db.execute(
            select(IdentityClusterMemberORM).where(
                IdentityClusterMemberORM.member_type == member_type.value,
                IdentityClusterMemberORM.member_key == key,
            )
        )
        return list(result.scalars().all())

    async def _cluster_has_other_users(
        self, db: AsyncSession, cluster_id: str, user_id: str | None
    ) -> bool:
        result = await db.execute(
            select(IdentityClusterMemberORM).where(
                IdentityClusterMemberORM.cluster_id == cluster_id,
                IdentityClusterMemberORM.member_type == ClusterMemberType.USER.value,
            )
        )
        users = [m.member_key for m in result.scalars().all()]
        if not users:
            return False
        if user_id is None:
            return True
        return any(u != user_id for u in users)


device_identity_service = DeviceIdentityService()
