"""Persisted hierarchy calibration error time series (Prompt 40)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import utcnow


class HierarchyCalibrationHistoryORM(Base):
    """Rolling calibration_error snapshots from hierarchy replay runs."""

    __tablename__ = "hierarchy_calibration_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    instrument_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    calibration_error: Mapped[float] = mapped_column(Float, nullable=False)
    brier_score: Mapped[float] = mapped_column(Float, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False)
    period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
