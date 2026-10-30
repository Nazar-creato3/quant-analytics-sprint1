"""Shared direction-accuracy scoring for live snapshots and health checks."""
from __future__ import annotations

from sqlalchemy import and_, func

from app.db.models import ForecastSnapshotResolution

DIRECTION_RETURN_THRESHOLD = 0.002
MIN_SCORED_SAMPLES = 5


def direction_from_return(ret: float, threshold: float = DIRECTION_RETURN_THRESHOLD) -> int:
    if ret > threshold:
        return 1
    if ret < -threshold:
        return -1
    return 0


def is_scored_resolution(predicted_direction: int, realized_return: float) -> bool:
    """True when both prediction and outcome are directional (non-neutral)."""
    if predicted_direction == 0:
        return False
    return direction_from_return(realized_return) != 0


def scored_resolution_clause():
    """SQLAlchemy filter excluding neutral predictions/outcomes from accuracy."""
    return and_(
        ForecastSnapshotResolution.predicted_direction != 0,
        func.abs(ForecastSnapshotResolution.realized_return) > DIRECTION_RETURN_THRESHOLD,
    )
