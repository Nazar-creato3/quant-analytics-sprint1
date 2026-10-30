"""Storage layers: raw archive, report snapshots, series history (Prompt 45)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.macro_registry import (
    MacroRawResponseORM,
    MacroReportSnapshotORM,
    MacroSeriesHistoryORM,
    MacroSeriesNormalizedORM,
)
from app.services.macro_registry.adapters.base import compute_payload_hash
from app.services.macro_registry.quality_gate import QualityGate
from app.services.macro_registry.types import RawResponse


class MacroStorageLayer:
    """Four-layer storage orchestration."""

    def __init__(self, quality_gate: QualityGate | None = None) -> None:
        self.quality_gate = quality_gate or QualityGate()

    async def store_raw_response(
        self,
        session: AsyncSession,
        raw: RawResponse,
    ) -> int | None:
        """Persist raw response; deduplicate by hash (Prompt 48)."""
        payload_hash = raw.payload_hash or compute_payload_hash(raw.payload)
        existing = (
            await session.execute(
                select(MacroRawResponseORM).where(
                    MacroRawResponseORM.source_id == raw.source_id,
                    MacroRawResponseORM.payload_hash == payload_hash,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id

        row = MacroRawResponseORM(
            source_id=raw.source_id,
            payload=raw.payload,
            content_type=raw.content_type,
            http_status=raw.http_status,
            payload_hash=payload_hash,
            fetched_at=raw.fetched_at,
        )
        session.add(row)
        await session.flush()
        return row.id

    async def build_report_snapshot(
        self,
        session: AsyncSession,
        *,
        snapshot_type: str,
        as_of: datetime | None = None,
        payload: dict[str, Any] | None = None,
        markdown: str | None = None,
    ) -> MacroReportSnapshotORM:
        ts = as_of or datetime.now(timezone.utc)
        snap = MacroReportSnapshotORM(
            id=str(uuid.uuid4()),
            snapshot_type=snapshot_type,
            as_of=ts,
            payload=payload or {},
            markdown=markdown,
            created_at=datetime.now(timezone.utc),
        )
        session.add(snap)
        await session.flush()
        return snap

    async def upsert_series_history(
        self,
        session: AsyncSession,
        *,
        instrument: str,
        period: str,
        value: float,
        quality_flag: str,
        as_of: datetime | None = None,
    ) -> None:
        ts = as_of or datetime.now(timezone.utc)
        row = MacroSeriesHistoryORM(
            instrument=instrument,
            period=period,
            value=Decimal(str(value)),
            quality_flag=quality_flag,
            as_of=ts,
        )
        session.merge(row)

    async def week_over_week_diff(
        self,
        session: AsyncSession,
        instrument: str,
        *,
        as_of: datetime | None = None,
    ) -> dict[str, Any] | None:
        return await self.period_diff(session, instrument, days=7, as_of=as_of)

    async def period_diff(
        self,
        session: AsyncSession,
        instrument: str,
        *,
        days: int,
        as_of: datetime | None = None,
    ) -> dict[str, Any] | None:
        ts = as_of or datetime.now(timezone.utc)
        prior_cutoff = ts - timedelta(days=days)
        current = await self._latest_history_value(session, instrument, before=ts)
        prior = await self._latest_history_value(session, instrument, before=prior_cutoff)
        if current is None or prior is None:
            return None
        delta = current - prior
        pct_change = (delta / prior * 100.0) if prior != 0 else 0.0
        return {
            "instrument": instrument,
            "current": current,
            "prior": prior,
            "delta": round(delta, 6),
            "pct_change": round(pct_change, 4),
            "horizon_days": days,
        }

    async def load_latest(
        self,
        session: AsyncSession,
        instrument: str,
    ) -> MacroSeriesNormalizedORM | None:
        stmt = (
            select(MacroSeriesNormalizedORM)
            .where(MacroSeriesNormalizedORM.instrument == instrument)
            .order_by(MacroSeriesNormalizedORM.observation_time.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def load_passing_latest(
        self,
        session: AsyncSession,
        instrument: str,
    ) -> MacroSeriesNormalizedORM | None:
        stmt = (
            select(MacroSeriesNormalizedORM)
            .where(
                MacroSeriesNormalizedORM.instrument == instrument,
                MacroSeriesNormalizedORM.quality_flag == "ok",
            )
            .order_by(MacroSeriesNormalizedORM.observation_time.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def archive_old_report_snapshots(
        self,
        session: AsyncSession,
        *,
        weeks: int = 12,
    ) -> int:
        """Mark old snapshots archived (retention — no hard delete)."""
        cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks)
        rows = list(
            (
                await session.execute(
                    select(MacroReportSnapshotORM).where(MacroReportSnapshotORM.as_of < cutoff)
                )
            ).scalars().all()
        )
        for row in rows:
            payload = dict(row.payload or {})
            if not payload.get("archived"):
                payload["archived"] = True
                row.payload = payload
        return len(rows)

    async def compact_raw_responses(
        self,
        session: AsyncSession,
        *,
        retention_years: int = 2,
    ) -> dict[str, int]:
        """Delete raw responses older than retention policy (never younger than 2 years)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=365 * retention_years)
        younger_count = (
            await session.execute(
                select(MacroRawResponseORM.id).where(MacroRawResponseORM.fetched_at >= cutoff).limit(1)
            )
        ).first()
        if younger_count is None:
            return {"deleted": 0, "retained": 0}

        delete_stmt = delete(MacroRawResponseORM).where(MacroRawResponseORM.fetched_at < cutoff)
        result = await session.execute(delete_stmt)
        deleted = int(result.rowcount or 0)
        retained = (
            await session.execute(select(MacroRawResponseORM.id).limit(1_000_000))
        ).all()
        return {"deleted": deleted, "retained": len(retained)}

    async def load_macro_indicators_as_of(
        self,
        session: AsyncSession,
        as_of: datetime,
    ) -> dict[str, float]:
        """Historical macro snapshot from normalized series (for hierarchy replay)."""
        from app.services.macro_registry.seed import INSTRUMENT_TO_LEGACY_CODE

        values: dict[str, float] = {}
        for instrument, legacy_code in INSTRUMENT_TO_LEGACY_CODE.items():
            row = await self._latest_normalized_before(session, instrument, as_of)
            if row is not None and row.quality_flag == "ok":
                values[legacy_code] = float(row.value)
        if "hy_oas" in values and "gov_10y" in values:
            values["credit_spread"] = round(values["hy_oas"] / 100.0 - values["gov_10y"] / 100.0, 6)
        return values

    async def _latest_normalized_before(
        self,
        session: AsyncSession,
        instrument: str,
        before: datetime,
    ) -> MacroSeriesNormalizedORM | None:
        stmt = (
            select(MacroSeriesNormalizedORM)
            .where(
                MacroSeriesNormalizedORM.instrument == instrument,
                MacroSeriesNormalizedORM.observation_time <= before,
            )
            .order_by(MacroSeriesNormalizedORM.observation_time.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def _latest_history_value(
        self,
        session: AsyncSession,
        instrument: str,
        *,
        before: datetime,
    ) -> float | None:
        stmt = (
            select(MacroSeriesHistoryORM)
            .where(
                MacroSeriesHistoryORM.instrument == instrument,
                MacroSeriesHistoryORM.as_of <= before,
                MacroSeriesHistoryORM.quality_flag == "ok",
            )
            .order_by(MacroSeriesHistoryORM.as_of.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return float(row.value) if row else None
