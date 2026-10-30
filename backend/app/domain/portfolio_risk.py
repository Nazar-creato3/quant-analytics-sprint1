"""Portfolio risk analytics persistence — Aladdin-style snapshot store.

Snapshots are append-only: each computation writes a new row so VaR/stress
numbers remain auditable with the exact holdings, window, and methodology
used that day.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import new_uuid, utcnow


class PortfolioRiskSnapshotORM(Base):
    """One computed risk report for a user's current book."""

    __tablename__ = "portfolio_risk_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    lookback_start: Mapped[date] = mapped_column(Date, nullable=False)
    lookback_end: Mapped[date] = mapped_column(Date, nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    var_method: Mapped[str] = mapped_column(String(40), nullable=False, default="historical_simulation")
    benchmark_symbol: Mapped[str] = mapped_column(String(20), nullable=False, default="SPY")
    var_95: Mapped[float | None] = mapped_column(Float, nullable=True)
    var_99: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_shortfall_95: Mapped[float | None] = mapped_column(Float, nullable=True)
    var_95_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    var_99_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_shortfall_95_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    alpha: Mapped[float | None] = mapped_column(Float, nullable=True)
    beta: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_squared: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_pairwise_correlation: Mapped[float | None] = mapped_column(Float, nullable=True)
    concentration_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    insufficient_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    holdings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    sector_weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_matrix: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    methodology: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    data_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
