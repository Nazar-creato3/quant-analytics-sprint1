"""Probabilistic market regime classification engine (Prompt 18)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.regime import RegimeHistoryORM
from app.services.regime.features import (
    aggregate_sector_prices,
    aggregate_sector_spread,
    aggregate_sector_volumes,
    average_pairwise_correlation,
    build_feature_sequence,
    sector_return_series,
)
from app.services.regime.hmm import classify_sequence
from app.services.regime.types import (
    InstrumentSeries,
    RegimeClassificationResult,
    RegimeScopeType,
)


class RegimeEngine:
    """Classify market state per instrument, sector, or global aggregate."""

    def classify_instrument(
        self,
        prices: list[float],
        volumes: list[float] | None = None,
        *,
        spread_bps: float | None = None,
        correlation_cluster: float = 0.0,
    ) -> RegimeClassificationResult:
        feature_sequence = build_feature_sequence(
            prices,
            volumes,
            spread_bps=spread_bps,
            correlation_cluster=correlation_cluster,
        )
        distribution, confidence = classify_sequence(feature_sequence)
        dominant = max(distribution, key=distribution.get)
        result = RegimeClassificationResult(
            distribution=distribution,
            dominant_regime=dominant,
            confidence=confidence,
            feature_sequence=tuple(feature_sequence),
        )
        result.validate()
        return result

    def classify_sector(
        self,
        instruments: dict[int, InstrumentSeries],
    ) -> RegimeClassificationResult:
        prices = aggregate_sector_prices(instruments)
        volumes = aggregate_sector_volumes(instruments)
        spread_bps = aggregate_sector_spread(instruments)
        correlation_cluster = average_pairwise_correlation(sector_return_series(instruments))
        return self.classify_instrument(
            prices,
            volumes,
            spread_bps=spread_bps,
            correlation_cluster=correlation_cluster,
        )

    def classify_global(
        self,
        sector_instruments: dict[str, dict[int, InstrumentSeries]],
    ) -> RegimeClassificationResult:
        flattened: dict[int, InstrumentSeries] = {}
        for instruments in sector_instruments.values():
            flattened.update(instruments)
        return self.classify_sector(flattened)

    async def get_previous_regime(
        self,
        session: AsyncSession,
        *,
        scope_type: RegimeScopeType,
        scope_id: str,
    ) -> str | None:
        stmt = (
            select(RegimeHistoryORM.dominant_regime)
            .where(
                RegimeHistoryORM.scope_type == scope_type.value,
                RegimeHistoryORM.scope_id == scope_id,
            )
            .order_by(RegimeHistoryORM.time.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def persist_classification(
        self,
        session: AsyncSession,
        *,
        scope_type: RegimeScopeType,
        scope_id: str,
        result: RegimeClassificationResult,
        observed_at: datetime,
        previous_regime: str | None = None,
    ) -> RegimeHistoryORM:
        if previous_regime is None:
            previous_regime = await self.get_previous_regime(
                session,
                scope_type=scope_type,
                scope_id=scope_id,
            )

        latest_features: dict[str, Any] | None = None
        if result.feature_sequence:
            latest_features = result.feature_sequence[-1].as_dict()

        row = RegimeHistoryORM(
            time=observed_at,
            scope_type=scope_type.value,
            scope_id=scope_id,
            regime_distribution=dict(result.distribution),
            dominant_regime=result.dominant_regime,
            confidence=result.confidence,
            previous_regime=previous_regime,
            features=latest_features,
        )
        session.add(row)
        await session.flush()
        return row

    async def classify_and_persist_instrument(
        self,
        session: AsyncSession,
        instrument_id: int,
        prices: list[float],
        volumes: list[float] | None = None,
        *,
        spread_bps: float | None = None,
        correlation_cluster: float = 0.0,
        observed_at: datetime,
    ) -> RegimeClassificationResult:
        result = self.classify_instrument(
            prices,
            volumes,
            spread_bps=spread_bps,
            correlation_cluster=correlation_cluster,
        )
        await self.persist_classification(
            session,
            scope_type=RegimeScopeType.INSTRUMENT,
            scope_id=str(instrument_id),
            result=result,
            observed_at=observed_at,
        )
        return result

    async def classify_and_persist_sector(
        self,
        session: AsyncSession,
        sector: str,
        instruments: dict[int, InstrumentSeries],
        *,
        observed_at: datetime,
    ) -> RegimeClassificationResult:
        result = self.classify_sector(instruments)
        await self.persist_classification(
            session,
            scope_type=RegimeScopeType.SECTOR,
            scope_id=sector,
            result=result,
            observed_at=observed_at,
        )
        return result

    async def classify_and_persist_global(
        self,
        session: AsyncSession,
        sector_instruments: dict[str, dict[int, InstrumentSeries]],
        *,
        observed_at: datetime,
    ) -> RegimeClassificationResult:
        result = self.classify_global(sector_instruments)
        await self.persist_classification(
            session,
            scope_type=RegimeScopeType.GLOBAL,
            scope_id="global",
            result=result,
            observed_at=observed_at,
        )
        return result
