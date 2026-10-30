"""Persistence for news_impact_history."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.news_impact import NewsImpactHistoryCreate, NewsImpactHistoryORM, NewsImpactHistoryRead
from app.services.event_risk.news_impact import NewsImpactAnalog


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class NewsImpactHistoryRepository:
    """CRUD helpers for news impact predictions and feedback."""

    async def create(self, db: AsyncSession, payload: NewsImpactHistoryCreate) -> NewsImpactHistoryORM:
        row = NewsImpactHistoryORM(
            news_id=payload.news_id,
            instrument_id=payload.instrument_id,
            sector=payload.sector,
            topic_tags=list(payload.topic_tags),
            predicted_probability=payload.predicted_probability,
            predicted_at=_ensure_utc(payload.predicted_at),
            daily_volatility=payload.daily_volatility,
            sigma_threshold=payload.sigma_threshold,
            metadata_=payload.metadata,
        )
        db.add(row)
        await db.flush()
        return row

    async def list_for_instrument(
        self,
        db: AsyncSession,
        instrument_id: int,
        *,
        limit: int = 500,
    ) -> list[NewsImpactHistoryRead]:
        result = await db.execute(
            select(NewsImpactHistoryORM)
            .where(
                NewsImpactHistoryORM.instrument_id == instrument_id,
                NewsImpactHistoryORM.feedback_at.is_not(None),
            )
            .order_by(NewsImpactHistoryORM.predicted_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [NewsImpactHistoryRead.model_validate(row) for row in rows]

    async def list_pending_feedback(
        self,
        db: AsyncSession,
        *,
        as_of: datetime,
        min_age_hours: int,
        limit: int = 200,
    ) -> list[NewsImpactHistoryORM]:
        cutoff = _ensure_utc(as_of)
        result = await db.execute(
            select(NewsImpactHistoryORM)
            .where(
                NewsImpactHistoryORM.feedback_at.is_(None),
                NewsImpactHistoryORM.predicted_at <= cutoff,
            )
            .order_by(NewsImpactHistoryORM.predicted_at.asc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
        return [
            row
            for row in rows
            if (cutoff - _ensure_utc(row.predicted_at)).total_seconds() >= min_age_hours * 3600
        ]

    async def apply_feedback(
        self,
        db: AsyncSession,
        row: NewsImpactHistoryORM,
        *,
        actual_move_sigma: float,
        actual_move_pct: float,
        strong_move: bool,
        feedback_at: datetime,
        feedback_horizon_hours: int,
        posterior_probability: float,
    ) -> NewsImpactHistoryORM:
        row.actual_move_sigma = actual_move_sigma
        row.actual_move_pct = actual_move_pct
        row.strong_move = strong_move
        row.feedback_at = _ensure_utc(feedback_at)
        row.feedback_horizon_hours = feedback_horizon_hours
        row.posterior_probability = posterior_probability
        await db.flush()
        return row

    @staticmethod
    def to_analogs(records: list[NewsImpactHistoryRead]) -> list[NewsImpactAnalog]:
        analogs: list[NewsImpactAnalog] = []
        for record in records:
            if record.strong_move is None:
                continue
            analogs.append(
                NewsImpactAnalog(
                    topic_tags=tuple(record.topic_tags),
                    strong_move=bool(record.strong_move),
                    predicted_probability=record.predicted_probability,
                )
            )
        return analogs
