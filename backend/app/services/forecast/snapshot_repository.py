"""Forecast snapshot persistence for daily Celery job."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ForecastSnapshot
from app.utils.helpers import utcnow

SNAPSHOT_SOURCE_LIVE = "live"
SNAPSHOT_SOURCE_BACKFILL = "backfill"


async def upsert_daily_snapshot(
    db: AsyncSession,
    *,
    instrument_id: int,
    symbol: str,
    payload: dict,
    snapshot_date: datetime | None = None,
    source: str = SNAPSHOT_SOURCE_LIVE,
) -> ForecastSnapshot:
    """Insert a new daily snapshot (one row per instrument per run)."""
    day = snapshot_date or utcnow()
    row = ForecastSnapshot(
        instrument_id=instrument_id,
        symbol=symbol.upper(),
        snapshot_date=day,
        payload=payload,
        source=source,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def snapshot_exists_for_day(
    db: AsyncSession,
    *,
    symbol: str,
    snapshot_date: datetime,
    source: str,
) -> bool:
    """Return True when a snapshot already exists for symbol/day/source."""
    day = snapshot_date.astimezone(timezone.utc).date()
    stmt = (
        select(func.count())
        .select_from(ForecastSnapshot)
        .where(
            ForecastSnapshot.symbol == symbol.upper(),
            ForecastSnapshot.source == source,
            func.date(ForecastSnapshot.snapshot_date) == day,
        )
    )
    count = (await db.execute(stmt)).scalar() or 0
    return int(count) > 0


async def delete_snapshots_for_day(
    db: AsyncSession,
    *,
    symbol: str,
    snapshot_date: datetime,
    source: str,
) -> int:
    """Delete snapshot rows (and dependent resolutions via FK or manual) for a day."""
    from sqlalchemy import delete

    from app.db.models import ForecastSnapshotResolution

    day = snapshot_date.astimezone(timezone.utc).date()
    ids_stmt = select(ForecastSnapshot.id).where(
        ForecastSnapshot.symbol == symbol.upper(),
        ForecastSnapshot.source == source,
        func.date(ForecastSnapshot.snapshot_date) == day,
    )
    ids = list((await db.execute(ids_stmt)).scalars().all())
    if not ids:
        return 0
    await db.execute(
        delete(ForecastSnapshotResolution).where(ForecastSnapshotResolution.snapshot_id.in_(ids))
    )
    result = await db.execute(delete(ForecastSnapshot).where(ForecastSnapshot.id.in_(ids)))
    await db.commit()
    return int(result.rowcount or 0)


async def latest_snapshot_for_symbol(db: AsyncSession, symbol: str) -> ForecastSnapshot | None:
    stmt = (
        select(ForecastSnapshot)
        .where(ForecastSnapshot.symbol == symbol.upper())
        .order_by(desc(ForecastSnapshot.snapshot_date))
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def latest_snapshots_for_symbols(
    db: AsyncSession,
    symbols: list[str],
) -> list[ForecastSnapshot]:
    rows: list[ForecastSnapshot] = []
    for symbol in symbols:
        row = await latest_snapshot_for_symbol(db, symbol)
        if row is not None:
            rows.append(row)
    return rows
