"""Feedback loop — reconcile predicted news impact with realized price moves."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.market_data import MarketOhlcvORM
from app.services.event_risk.news_impact import (
    compute_actual_move_sigma,
    is_strong_move,
    update_posterior_from_feedback,
)
from app.services.event_risk.news_impact_repository import NewsImpactHistoryRepository


class NewsImpactFeedbackService:
    """Update news_impact_history after 4h/1d observation windows."""

    def __init__(
        self,
        *,
        repository: NewsImpactHistoryRepository | None = None,
        feedback_horizons_hours: tuple[int, ...] = (4, 24),
    ) -> None:
        self._repository = repository or NewsImpactHistoryRepository()
        self._feedback_horizons_hours = feedback_horizons_hours

    async def process_pending(self, db: AsyncSession, *, as_of: datetime | None = None) -> int:
        now = self._utc(as_of)
        updated = 0

        for horizon in self._feedback_horizons_hours:
            pending = await self._repository.list_pending_feedback(
                db,
                as_of=now,
                min_age_hours=horizon,
            )
            for row in pending:
                if row.instrument_id is None:
                    continue
                if row.feedback_at is not None:
                    continue
                if row.metadata_.get("feedback_attempted_horizons", {}).get(str(horizon)):
                    continue

                price_at_news = await self._price_near(
                    db,
                    instrument_id=row.instrument_id,
                    target_time=row.predicted_at,
                )
                price_after = await self._price_near(
                    db,
                    instrument_id=row.instrument_id,
                    target_time=row.predicted_at,
                    offset_hours=horizon,
                )
                if price_at_news is None or price_after is None:
                    await self._mark_attempt(row, horizon)
                    continue

                daily_vol = float(row.daily_volatility or 0.0)
                move_pct, move_sigma = compute_actual_move_sigma(
                    price_at_news=price_at_news,
                    price_after=price_after,
                    daily_volatility=daily_vol,
                )
                strong = is_strong_move(move_sigma, sigma_threshold=float(row.sigma_threshold))
                posterior = update_posterior_from_feedback(
                    predicted_probability=float(row.predicted_probability),
                    strong_move=strong,
                )
                await self._repository.apply_feedback(
                    db,
                    row,
                    actual_move_sigma=move_sigma,
                    actual_move_pct=move_pct,
                    strong_move=strong,
                    feedback_at=now,
                    feedback_horizon_hours=horizon,
                    posterior_probability=posterior,
                )
                updated += 1

        return updated

    async def _price_near(
        self,
        db: AsyncSession,
        *,
        instrument_id: int,
        target_time: datetime,
        offset_hours: int = 0,
    ) -> float | None:
        anchor = self._utc(target_time)
        if offset_hours:
            anchor = anchor + timedelta(hours=offset_hours)

        result = await db.execute(
            select(MarketOhlcvORM)
            .where(
                MarketOhlcvORM.instrument_id == instrument_id,
                MarketOhlcvORM.time <= anchor,
            )
            .order_by(MarketOhlcvORM.time.desc())
            .limit(1)
        )
        bar = result.scalar_one_or_none()
        if bar is None or bar.close is None:
            return None
        return float(bar.close)

    async def _mark_attempt(self, row, horizon: int) -> None:
        attempted = dict(row.metadata_.get("feedback_attempted_horizons", {}))
        attempted[str(horizon)] = True
        row.metadata_["feedback_attempted_horizons"] = attempted

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
