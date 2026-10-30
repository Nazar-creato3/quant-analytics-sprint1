"""Rolling live direction accuracy from resolved forecast snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ForecastSnapshot, ForecastSnapshotResolution
from app.services.forecast.direction_accuracy import MIN_SCORED_SAMPLES, scored_resolution_clause
from app.services.forecast.snapshot_repository import SNAPSHOT_SOURCE_LIVE
from app.utils.wilson_ci import wilson_ci, wilson_ci_from_rate

LIVE_ACCURACY_FLOOR = 0.45
LIVE_ACCURACY_WINDOW_DAYS = 30
MIN_LIVE_SAMPLES_FOR_SUPPRESSION = MIN_SCORED_SAMPLES
HEALTH_ACCURACY_FLOOR = 0.50

DIRECTION_SUPPRESSION_MESSAGE_RU = (
    "недостаточно предсказательной силы для направления"
)


@dataclass(frozen=True, slots=True)
class RollingLiveAccuracy:
    symbol: str
    horizon_days: int
    window_days: int
    accuracy: float | None
    sample_size: int
    ci_low: float | None = None
    ci_high: float | None = None
    source_filter: str = SNAPSHOT_SOURCE_LIVE
    hits: int = 0

    @property
    def should_suppress_direction(self) -> bool:
        if self.sample_size < MIN_LIVE_SAMPLES_FOR_SUPPRESSION:
            return False
        if self.accuracy is None:
            return False
        return self.accuracy < LIVE_ACCURACY_FLOOR


async def rolling_live_direction_accuracy(
    db: AsyncSession,
    *,
    symbol: str,
    horizon_days: int = 10,
    window_days: int = LIVE_ACCURACY_WINDOW_DAYS,
    source: str = SNAPSHOT_SOURCE_LIVE,
) -> RollingLiveAccuracy:
    """Compute trailing live binary direction accuracy from resolved snapshots.

    Only directional predictions with directional realized returns are scored;
    neutral predictions/outcomes are excluded from the denominator.
    """
    sym = symbol.upper()
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    live_snapshot_ids = (
        select(ForecastSnapshot.id)
        .where(
            ForecastSnapshot.symbol == sym,
            ForecastSnapshot.source == source,
        )
        .scalar_subquery()
    )
    stmt = (
        select(
            func.count().label("n"),
            func.sum(cast(ForecastSnapshotResolution.direction_hit, Integer)).label("hits"),
        )
        .where(
            and_(
                ForecastSnapshotResolution.symbol == sym,
                ForecastSnapshotResolution.horizon_days == horizon_days,
                ForecastSnapshotResolution.resolved_at >= cutoff,
                ForecastSnapshotResolution.snapshot_id.in_(live_snapshot_ids),
                scored_resolution_clause(),
            )
        )
    )
    row = (await db.execute(stmt)).one()
    n = int(row.n or 0)
    hits = int(row.hits or 0)
    acc = (hits / n) if n > 0 else None
    interval = wilson_ci(hits, n) if n > 0 else None
    return RollingLiveAccuracy(
        symbol=sym,
        horizon_days=horizon_days,
        window_days=window_days,
        accuracy=acc,
        sample_size=n,
        ci_low=interval.ci_low if interval else None,
        ci_high=interval.ci_high if interval else None,
        source_filter=source,
        hits=hits,
    )
