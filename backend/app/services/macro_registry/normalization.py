"""Normalization layer — unified schema with revision history (Prompt 43)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.macro_registry import MacroSeriesNormalizedORM
from app.services.macro_registry.transformers import TRANSFORMER_REGISTRY
from app.services.macro_registry.types import InternalObservation, NormalizedObservation


class NormalizationLayer:
    """Apply registered transformers and persist normalized observations."""

    def transform_batch(
        self,
        *,
        transformer_name: str,
        source_id: str,
        observations: list[InternalObservation],
        raw_payload_hash: str,
    ) -> list[NormalizedObservation]:
        fn = TRANSFORMER_REGISTRY.get(transformer_name)
        if fn is None:
            raise ValueError(f"Unknown transformer: {transformer_name}")

        if transformer_name == "transform_fred_cpi_yoy":
            result = fn(observations, source_id=source_id, raw_payload_hash=raw_payload_hash)
            return list(result)

        normalized: list[NormalizedObservation] = []
        for obs in observations:
            item = fn(obs, source_id=source_id, raw_payload_hash=raw_payload_hash)
            if isinstance(item, list):
                normalized.extend(item)
            else:
                normalized.append(item)
        return normalized

    async def persist_observations(
        self,
        session: AsyncSession,
        *,
        raw_response_id: int,
        observations: list[NormalizedObservation],
        quality_flags: dict[tuple[str, datetime], str] | None = None,
    ) -> int:
        """Insert new revisions without overwriting prior rows."""
        flags = quality_flags or {}
        stored = 0
        now = datetime.now(timezone.utc)
        for obs in observations:
            key = (obs.instrument, obs.observation_time)
            quality = flags.get(key, "ok")
            revision = await self._next_revision(
                session,
                instrument=obs.instrument,
                observation_time=obs.observation_time,
                source_id=obs.source_id,
                value=obs.value,
            )
            existing = await self._find_existing(
                session,
                instrument=obs.instrument,
                observation_time=obs.observation_time,
                source_id=obs.source_id,
                revision=revision,
            )
            if existing is not None and float(existing.value) == obs.value:
                if existing.quality_flag != quality:
                    existing.quality_flag = quality
                continue
            row = MacroSeriesNormalizedORM(
                instrument=obs.instrument,
                source_id=obs.source_id,
                raw_response_id=raw_response_id,
                value=Decimal(str(obs.value)),
                currency=obs.currency,
                unit=obs.unit,
                release_time=obs.release_time,
                observation_time=obs.observation_time,
                period=obs.period,
                revision=revision,
                quality_flag=quality,
                confidence=obs.confidence,
                raw_payload_hash=obs.raw_payload_hash,
                created_at=now,
            )
            session.add(row)
            stored += 1
        await session.flush()
        return stored

    async def _next_revision(
        self,
        session: AsyncSession,
        *,
        instrument: str,
        observation_time: datetime,
        source_id: str,
        value: float,
    ) -> int:
        stmt = (
            select(MacroSeriesNormalizedORM)
            .where(
                MacroSeriesNormalizedORM.instrument == instrument,
                MacroSeriesNormalizedORM.observation_time == observation_time,
                MacroSeriesNormalizedORM.source_id == source_id,
            )
            .order_by(MacroSeriesNormalizedORM.revision.desc())
            .limit(1)
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            return 0
        if float(existing.value) == value:
            return existing.revision
        return existing.revision + 1

    async def _find_existing(
        self,
        session: AsyncSession,
        *,
        instrument: str,
        observation_time: datetime,
        source_id: str,
        revision: int,
    ) -> MacroSeriesNormalizedORM | None:
        stmt = select(MacroSeriesNormalizedORM).where(
            MacroSeriesNormalizedORM.instrument == instrument,
            MacroSeriesNormalizedORM.observation_time == observation_time,
            MacroSeriesNormalizedORM.source_id == source_id,
            MacroSeriesNormalizedORM.revision == revision,
        )
        return (await session.execute(stmt)).scalar_one_or_none()
