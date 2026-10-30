"""Persistence for active_locks with TTL."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.active_lock import ActiveLockCreate, ActiveLockORM, ActiveLockRead, ActiveLockType


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ActiveLockRepository:
    """CRUD helpers for temporary news/event locks."""

    async def create(self, db: AsyncSession, payload: ActiveLockCreate) -> ActiveLockORM:
        row = ActiveLockORM(
            lock_type=payload.lock_type.value,
            instrument_id=payload.instrument_id,
            sleeve_id=payload.sleeve_id,
            sector=payload.sector,
            news_shock_score=payload.news_shock_score,
            reason=payload.reason,
            source_event_id=payload.source_event_id,
            expires_at=_ensure_utc(payload.expires_at),
            metadata_=payload.metadata,
        )
        db.add(row)
        await db.flush()
        return row

    async def list_active(self, db: AsyncSession, *, as_of: datetime | None = None) -> list[ActiveLockRead]:
        now = _ensure_utc(as_of or datetime.now(timezone.utc))
        result = await db.execute(
            select(ActiveLockORM)
            .where(ActiveLockORM.expires_at > now)
            .order_by(ActiveLockORM.created_at.desc())
        )
        rows = result.scalars().all()
        return [ActiveLockRead.model_validate(row) for row in rows]

    async def locked_instrument_ids(
        self,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> frozenset[int]:
        now = _ensure_utc(as_of or datetime.now(timezone.utc))
        result = await db.execute(
            select(ActiveLockORM.instrument_id)
            .where(
                ActiveLockORM.expires_at > now,
                ActiveLockORM.instrument_id.is_not(None),
            )
        )
        return frozenset(value for value in result.scalars().all() if value is not None)

    async def locked_sleeve_ids(
        self,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> frozenset[str]:
        now = _ensure_utc(as_of or datetime.now(timezone.utc))
        result = await db.execute(
            select(ActiveLockORM.sleeve_id)
            .where(
                ActiveLockORM.expires_at > now,
                ActiveLockORM.sleeve_id.is_not(None),
            )
        )
        return frozenset(value for value in result.scalars().all() if value is not None)

    async def locked_sectors(
        self,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> frozenset[str]:
        now = _ensure_utc(as_of or datetime.now(timezone.utc))
        result = await db.execute(
            select(ActiveLockORM.sector)
            .where(
                ActiveLockORM.expires_at > now,
                ActiveLockORM.sector.is_not(None),
            )
        )
        return frozenset(value for value in result.scalars().all() if value)

    async def expire_stale(self, db: AsyncSession, *, as_of: datetime | None = None) -> int:
        now = _ensure_utc(as_of or datetime.now(timezone.utc))
        result = await db.execute(delete(ActiveLockORM).where(ActiveLockORM.expires_at <= now))
        return int(result.rowcount or 0)

    async def has_active_lock(
        self,
        db: AsyncSession,
        *,
        instrument_id: int | None = None,
        sleeve_id: str | None = None,
        sector: str | None = None,
        lock_type: ActiveLockType | None = None,
        as_of: datetime | None = None,
    ) -> bool:
        now = _ensure_utc(as_of or datetime.now(timezone.utc))
        query = select(ActiveLockORM.id).where(ActiveLockORM.expires_at > now)
        if instrument_id is not None:
            query = query.where(ActiveLockORM.instrument_id == instrument_id)
        if sleeve_id is not None:
            query = query.where(ActiveLockORM.sleeve_id == sleeve_id)
        if sector is not None:
            query = query.where(ActiveLockORM.sector == sector)
        if lock_type is not None:
            query = query.where(ActiveLockORM.lock_type == lock_type.value)
        result = await db.execute(query.limit(1))
        return result.scalar_one_or_none() is not None

    async def locked_instrument_ids_by_type(
        self,
        db: AsyncSession,
        *,
        lock_type: ActiveLockType,
        as_of: datetime | None = None,
    ) -> frozenset[int]:
        now = _ensure_utc(as_of or datetime.now(timezone.utc))
        result = await db.execute(
            select(ActiveLockORM.instrument_id).where(
                ActiveLockORM.expires_at > now,
                ActiveLockORM.instrument_id.is_not(None),
                ActiveLockORM.lock_type == lock_type.value,
            )
        )
        return frozenset(value for value in result.scalars().all() if value is not None)

    async def release_locks(
        self,
        db: AsyncSession,
        *,
        instrument_id: int | None = None,
        sleeve_id: str | None = None,
        sector: str | None = None,
        lock_type: ActiveLockType | None = None,
    ) -> int:
        query = delete(ActiveLockORM)
        if instrument_id is not None:
            query = query.where(ActiveLockORM.instrument_id == instrument_id)
        if sleeve_id is not None:
            query = query.where(ActiveLockORM.sleeve_id == sleeve_id)
        if sector is not None:
            query = query.where(ActiveLockORM.sector == sector)
        if lock_type is not None:
            query = query.where(ActiveLockORM.lock_type == lock_type.value)
        result = await db.execute(query)
        return int(result.rowcount or 0)
