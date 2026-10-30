"""Persistence layer for factor_exposure (Prompt 19)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.market_data import FactorExposureORM
from app.services.factor.types import ALL_FACTORS, FactorExposureRow, FactorName


class FactorExposureRepository:
    """Write/read factor decomposition results."""

    async def upsert_exposures(
        self,
        session: AsyncSession,
        rows: list[FactorExposureRow],
    ) -> int:
        if not rows:
            return 0
        payload = [
            {
                "instrument_id": row.instrument_id,
                "time": row.time,
                "factor_name": row.factor_name.value,
                "beta": Decimal(str(round(row.beta, 8))),
                "r_squared_of_model": Decimal(str(round(row.r_squared_of_model, 8))),
            }
            for row in rows
        ]
        stmt = insert(FactorExposureORM).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["instrument_id", "time", "factor_name"],
            set_={
                "beta": stmt.excluded.beta,
                "r_squared_of_model": stmt.excluded.r_squared_of_model,
            },
        )
        await session.execute(stmt)
        await session.commit()
        return len(rows)

    async def store_model_snapshot(
        self,
        session: AsyncSession,
        *,
        instrument_id: int,
        timestamp: datetime,
        betas: dict[FactorName, float],
        r_squared: float,
    ) -> int:
        rows = [
            FactorExposureRow(
                instrument_id=instrument_id,
                time=timestamp,
                factor_name=factor_name,
                beta=beta,
                r_squared_of_model=r_squared,
            )
            for factor_name, beta in betas.items()
        ]
        return await self.upsert_exposures(session, rows)

    async def latest_exposures(
        self,
        session: AsyncSession,
        instrument_id: int,
        *,
        limit: int = 1,
    ) -> list[FactorExposureRow]:
        """Return the most recent factor snapshots (all factors per timestamp)."""
        times_stmt = (
            select(FactorExposureORM.time)
            .where(FactorExposureORM.instrument_id == instrument_id)
            .distinct()
            .order_by(desc(FactorExposureORM.time))
            .limit(limit)
        )
        times_result = await session.execute(times_stmt)
        timestamps = [row[0] for row in times_result.all()]
        if not timestamps:
            return []

        rows_stmt = (
            select(FactorExposureORM)
            .where(
                FactorExposureORM.instrument_id == instrument_id,
                FactorExposureORM.time.in_(timestamps),
            )
            .order_by(desc(FactorExposureORM.time), FactorExposureORM.factor_name)
        )
        rows_result = await session.execute(rows_stmt)
        return [
            FactorExposureRow(
                instrument_id=row.instrument_id,
                time=row.time,
                factor_name=FactorName(row.factor_name),
                beta=float(row.beta),
                r_squared_of_model=float(row.r_squared_of_model),
            )
            for row in rows_result.scalars().all()
            if row.factor_name in {factor.value for factor in ALL_FACTORS}
        ]
