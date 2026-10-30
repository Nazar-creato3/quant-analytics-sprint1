"""Rolling calibration_error for live forecasts (Prompt 37)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prediction_hierarchy.confidence_calibrator import compute_calibration_error

GLOBAL_MACRO_SCOPE_TYPE = "global_macro"
GLOBAL_MACRO_SCOPE_ID = "default"

_MAX_ROLLING_PAIRS = 200
_lock = Lock()
_rolling_confidences: deque[float] = deque(maxlen=_MAX_ROLLING_PAIRS)
_rolling_outcomes: deque[bool] = deque(maxlen=_MAX_ROLLING_PAIRS)


@dataclass(frozen=True, slots=True)
class CalibrationRunSnapshot:
    calibration_error: float
    brier_score: float
    total_points: int
    period_days: int


def record_validation_pairs(confidences: list[float], outcomes: list[bool]) -> None:
    """Append replay validation pairs to the in-process rolling window."""
    if not confidences or len(confidences) != len(outcomes):
        return
    with _lock:
        for confidence, outcome in zip(confidences, outcomes):
            _rolling_confidences.append(confidence)
            _rolling_outcomes.append(outcome)


def get_live_calibration_error(*, min_pairs: int = 20) -> float | None:
    """Rolling calibration_error from recent hierarchy validation pairs."""
    with _lock:
        confidences = list(_rolling_confidences)
        outcomes = list(_rolling_outcomes)
    if len(confidences) < min_pairs:
        return None
    return compute_calibration_error(confidences, outcomes)


async def persist_calibration_run(
    session: AsyncSession,
    *,
    instrument_id: int,
    snapshot: CalibrationRunSnapshot,
    run_at: datetime | None = None,
) -> None:
    from app.domain.hierarchy_calibration import HierarchyCalibrationHistoryORM

    ts = run_at or datetime.now(timezone.utc)
    row = HierarchyCalibrationHistoryORM(
        run_at=ts,
        instrument_id=instrument_id,
        calibration_error=snapshot.calibration_error,
        brier_score=snapshot.brier_score,
        total_points=snapshot.total_points,
        period_days=snapshot.period_days,
    )
    session.add(row)
    await session.flush()


async def load_recent_calibration_error(
    session: AsyncSession,
    *,
    instrument_id: int | None = None,
    limit: int = 10,
) -> float | None:
    """Average calibration_error from persisted replay runs (DB fallback)."""
    from app.domain.hierarchy_calibration import HierarchyCalibrationHistoryORM

    stmt = select(HierarchyCalibrationHistoryORM).order_by(
        HierarchyCalibrationHistoryORM.run_at.desc()
    )
    if instrument_id is not None:
        stmt = stmt.where(HierarchyCalibrationHistoryORM.instrument_id == instrument_id)
    stmt = stmt.limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return None
    return round(sum(row.calibration_error for row in rows) / len(rows), 6)


async def resolve_live_calibration_error(
    session: AsyncSession,
    *,
    instrument_id: int | None = None,
) -> float | None:
    """Prefer in-process rolling window; fall back to DB history."""
    live = get_live_calibration_error()
    if live is not None:
        return live
    return await load_recent_calibration_error(session, instrument_id=instrument_id)
