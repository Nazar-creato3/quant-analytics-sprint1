"""Live signal performance and model drift API (spec A.7–A.8)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db
from app.db.models import User
from app.services.monitoring.model_drift import compute_model_drift, empty_model_drift
from app.services.monitoring.signal_performance import (
    compute_live_maneuver_performance,
    empty_live_performance,
)
from sqlalchemy import select

router = APIRouter(prefix="/signal-monitoring", tags=["signal-monitoring"])


@router.get("/live-performance")
async def live_performance(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Live maneuver KPIs — clearly labeled, never mixed with backtest."""
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    if user is None:
        return empty_live_performance().to_dict()
    metrics = await compute_live_maneuver_performance(
        db,
        owner_user_id=user.id,
    )
    return metrics.to_dict()


@router.get("/model-drift")
async def model_drift(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    if user is None:
        return empty_model_drift().to_dict()
    snapshot = await compute_model_drift(db, owner_user_id=user.id)
    return snapshot.to_dict()
