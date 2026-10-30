"""KillSwitch — halt trading, cancel intents, require manual unlock."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import new_uuid
from app.domain.deal_intent import DealIntentORM, transition_deal_intent_status
from app.domain.deal_intent_enums import DealIntentStatus
from app.domain.deal_intent_fsm import DealIntentEvent
from app.domain.kill_switch import KillSwitchStateORM
from app.domain.profile import ProfileORM
from app.domain.sleeve import SleeveORM
from app.services.control_fabric.strategy_halt import (
    REDIS_KILL_FLAG_PREFIX,
    REDIS_SYSTEM_KILL_FLAG,
)
from app.services.control_fabric.types import KillSwitchScope, KillSwitchStatus, KillSwitchTrigger
from app.utils.cache import cache_set
from app.utils.helpers import utcnow

_PENDING_STATUSES = (
    DealIntentStatus.DRAFT.value,
    DealIntentStatus.PENDING_APPROVAL.value,
    DealIntentStatus.APPROVED.value,
    DealIntentStatus.HELD.value,
)
_ACTIVE_STATUSES = _PENDING_STATUSES + (DealIntentStatus.EXECUTING.value,)


class KillSwitchService:
    """Global trading halt with mandatory comment on unlock."""

    async def is_active(
        self,
        db: AsyncSession,
        *,
        profile_id: str | None = None,
        sleeve_id: str | None = None,
    ) -> KillSwitchStatus:
        if await self._has_active(db, KillSwitchScope.SYSTEM, None):
            row = await self._load_active(db, KillSwitchScope.SYSTEM, None)
            return self._to_status(row)

        if profile_id and await self._has_active(db, KillSwitchScope.PROFILE, profile_id):
            row = await self._load_active(db, KillSwitchScope.PROFILE, profile_id)
            return self._to_status(row)

        if sleeve_id and await self._has_active(db, KillSwitchScope.SLEEVE, sleeve_id):
            row = await self._load_active(db, KillSwitchScope.SLEEVE, sleeve_id)
            return self._to_status(row)

        return KillSwitchStatus(
            active=False,
            scope=KillSwitchScope.SYSTEM,
            scope_id=None,
            trigger_type=None,
            reason=None,
        )

    async def trigger(
        self,
        db: AsyncSession,
        *,
        scope: KillSwitchScope,
        scope_id: str | None,
        reason: str,
        trigger_type: KillSwitchTrigger,
        triggered_by: str | None = None,
        cancel_intents: bool = True,
        stop_strategies: bool = True,
    ) -> KillSwitchStateORM:
        if scope != KillSwitchScope.SYSTEM and not scope_id:
            raise ValueError(f"scope_id required for {scope.value} kill switch")

        existing = await self._load_active(db, scope, scope_id)
        if existing is not None:
            return existing

        row = KillSwitchStateORM(
            id=new_uuid(),
            scope=scope.value,
            scope_id=scope_id,
            active=True,
            trigger_type=trigger_type.value,
            reason=reason.strip(),
            triggered_by=triggered_by,
        )
        db.add(row)

        if cancel_intents:
            await self._cancel_intents(db, scope=scope, scope_id=scope_id, reason=reason)
        if stop_strategies:
            await self._stop_strategies(db, scope=scope, scope_id=scope_id, reason=reason)

        return row

    async def unlock(
        self,
        db: AsyncSession,
        *,
        scope: KillSwitchScope,
        scope_id: str | None,
        comment: str,
        unlocked_by: str | None = None,
    ) -> KillSwitchStateORM:
        normalized = comment.strip()
        if not normalized:
            raise ValueError("unlock comment is mandatory")

        row = await self._load_active(db, scope, scope_id)
        if row is None:
            raise ValueError(f"no active kill switch for scope={scope.value} id={scope_id!r}")

        row.active = False
        row.unlock_comment = normalized
        row.unlocked_by = unlocked_by
        row.unlocked_at = utcnow()
        return row

    async def _cancel_intents(
        self,
        db: AsyncSession,
        *,
        scope: KillSwitchScope,
        scope_id: str | None,
        reason: str,
    ) -> int:
        query = select(DealIntentORM).where(DealIntentORM.status.in_(_ACTIVE_STATUSES))

        if scope == KillSwitchScope.SLEEVE and scope_id:
            query = query.where(DealIntentORM.sleeve_id == scope_id)
        elif scope == KillSwitchScope.PROFILE and scope_id:
            query = query.join(SleeveORM, DealIntentORM.sleeve_id == SleeveORM.id).where(
                SleeveORM.profile_id == scope_id
            )

        result = await db.execute(query)
        cancelled = 0
        for intent_row in result.scalars().all():
            current = DealIntentStatus(intent_row.status)
            if current == DealIntentStatus.EXECUTING:
                event = DealIntentEvent.CANCEL
            elif current == DealIntentStatus.HELD:
                event = DealIntentEvent.CANCEL
            elif current in {
                DealIntentStatus.PENDING_APPROVAL,
                DealIntentStatus.APPROVED,
            }:
                event = DealIntentEvent.CANCEL
            elif current == DealIntentStatus.DRAFT:
                event = DealIntentEvent.CANCEL
            else:
                continue
            try:
                next_status = transition_deal_intent_status(current, event)
            except ValueError:
                continue
            intent_row.status = next_status.value
            intent_row.updated_at = utcnow()
            exit_logic = dict(intent_row.exit_logic or {})
            exit_logic["kill_switch_cancel_reason"] = reason
            intent_row.exit_logic = exit_logic
            cancelled += 1
        return cancelled

    async def _stop_strategies(
        self,
        db: AsyncSession,
        *,
        scope: KillSwitchScope,
        scope_id: str | None,
        reason: str,
    ) -> None:
        if scope == KillSwitchScope.SYSTEM:
            result = await db.execute(select(ProfileORM))
            profiles = result.scalars().all()
        elif scope == KillSwitchScope.PROFILE and scope_id:
            result = await db.execute(select(ProfileORM).where(ProfileORM.id == scope_id))
            profiles = list(result.scalars().all())
        elif scope == KillSwitchScope.SLEEVE and scope_id:
            sleeve_result = await db.execute(select(SleeveORM).where(SleeveORM.id == scope_id))
            sleeve = sleeve_result.scalar_one_or_none()
            if sleeve is None:
                return
            result = await db.execute(select(ProfileORM).where(ProfileORM.id == sleeve.profile_id))
            profiles = list(result.scalars().all())
        else:
            return

        for profile in profiles:
            prefs: dict[str, Any] = deepcopy(profile.session_preferences or {})
            prefs["strategies_stopped"] = True
            prefs["strategies_stop_reason"] = reason
            prefs["strategies_stopped_at"] = utcnow().isoformat()
            if scope == KillSwitchScope.SLEEVE and scope_id:
                stopped = set(prefs.get("stopped_sleeve_ids") or [])
                stopped.add(scope_id)
                prefs["stopped_sleeve_ids"] = sorted(stopped)
            profile.session_preferences = prefs
            profile.updated_at = utcnow()

        await self._publish_strategy_halt_flags(
            scope=scope,
            scope_id=scope_id,
            profiles=profiles,
            reason=reason,
        )

    async def _publish_strategy_halt_flags(
        self,
        *,
        scope: KillSwitchScope,
        scope_id: str | None,
        profiles: list[ProfileORM],
        reason: str,
    ) -> None:
        """Mirror DB halt flags to Redis so Celery ticks observe kill switch within one interval."""
        payload = {"reason": reason, "halted_at": utcnow().isoformat()}
        ttl = 86_400 * 7
        if scope == KillSwitchScope.SYSTEM:
            await cache_set(REDIS_SYSTEM_KILL_FLAG, payload, ttl=ttl)
            for profile in profiles:
                await cache_set(f"{REDIS_KILL_FLAG_PREFIX}:{profile.id}", payload, ttl=ttl)
        elif scope == KillSwitchScope.PROFILE and scope_id:
            await cache_set(f"{REDIS_KILL_FLAG_PREFIX}:{scope_id}", payload, ttl=ttl)
        elif scope == KillSwitchScope.SLEEVE and scope_id:
            await cache_set(f"{REDIS_KILL_FLAG_PREFIX}:sleeve:{scope_id}", payload, ttl=ttl)

    async def _has_active(
        self,
        db: AsyncSession,
        scope: KillSwitchScope,
        scope_id: str | None,
    ) -> bool:
        return await self._load_active(db, scope, scope_id) is not None

    async def _load_active(
        self,
        db: AsyncSession,
        scope: KillSwitchScope,
        scope_id: str | None,
    ) -> KillSwitchStateORM | None:
        query = select(KillSwitchStateORM).where(
            KillSwitchStateORM.scope == scope.value,
            KillSwitchStateORM.active.is_(True),
        )
        if scope_id is None:
            query = query.where(KillSwitchStateORM.scope_id.is_(None))
        else:
            query = query.where(KillSwitchStateORM.scope_id == scope_id)

        result = await db.execute(query.order_by(KillSwitchStateORM.triggered_at.desc()).limit(1))
        return result.scalar_one_or_none()

    @staticmethod
    def _to_status(row: KillSwitchStateORM | None) -> KillSwitchStatus:
        if row is None:
            return KillSwitchStatus(
                active=False,
                scope=KillSwitchScope.SYSTEM,
                scope_id=None,
                trigger_type=None,
                reason=None,
            )
        return KillSwitchStatus(
            active=row.active,
            scope=KillSwitchScope(row.scope),
            scope_id=row.scope_id,
            trigger_type=KillSwitchTrigger(row.trigger_type),
            reason=row.reason,
        )
