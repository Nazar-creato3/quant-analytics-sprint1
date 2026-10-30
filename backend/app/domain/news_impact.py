"""News impact history ORM — feedback store for Prompt 24."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class NewsImpactHistoryORM(Base):
    __tablename__ = "news_impact_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    instrument_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("instruments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    predicted_probability: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    daily_volatility: Mapped[float | None] = mapped_column(Float, nullable=True)
    sigma_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    actual_move_sigma: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_move_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    strong_move: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feedback_horizon_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posterior_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class NewsImpactHistoryCreate(BaseModel):
    news_id: str | None = None
    instrument_id: int | None = None
    sector: str | None = None
    topic_tags: list[str] = Field(default_factory=list)
    predicted_probability: float = Field(ge=0.0, le=1.0)
    predicted_at: datetime
    daily_volatility: float | None = None
    sigma_threshold: float = 2.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class NewsImpactHistoryRead(NewsImpactHistoryCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actual_move_sigma: float | None = None
    actual_move_pct: float | None = None
    strong_move: bool | None = None
    feedback_at: datetime | None = None
    feedback_horizon_hours: int | None = None
    posterior_probability: float | None = None


__all__ = [
    "NewsImpactHistoryCreate",
    "NewsImpactHistoryORM",
    "NewsImpactHistoryRead",
]
