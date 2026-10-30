"""ORM models for Macro Registry pipeline (Prompts 41-50)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class MacroSourceRegistryORM(Base):
    """Configuration registry for macro data sources (Prompt 41)."""

    __tablename__ = "macro_source_registry"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_interval: Mapped[str] = mapped_column(String(64), nullable=False, default="0 8 * * *")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fallback_source: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("macro_source_registry.source_id"),
        nullable=True,
    )
    transformer: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_successful_refresh: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reliability_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    fallback = relationship(
        "MacroSourceRegistryORM",
        remote_side="MacroSourceRegistryORM.source_id",
        foreign_keys=[fallback_source],
    )


class MacroRawResponseORM(Base):
    """Immutable archive of source HTTP responses (Prompt 42)."""

    __tablename__ = "macro_raw_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("macro_source_registry.source_id"),
        nullable=False,
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/json")
    http_status: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("source_id", "payload_hash", name="macro_raw_responses_source_hash_key"),
    )


class MacroSeriesNormalizedORM(Base):
    """Normalized macro series with full revision history (Prompt 43/48)."""

    __tablename__ = "macro_series_normalized"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("macro_source_registry.source_id"),
        nullable=False,
    )
    raw_response_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("macro_raw_responses.id"),
        nullable=False,
    )
    value: Mapped[Decimal] = mapped_column(nullable=False)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    release_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_flag: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    raw_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "instrument",
            "observation_time",
            "source_id",
            "revision",
            name="macro_series_normalized_instrument_obs_rev_key",
        ),
    )


class MacroReportSnapshotORM(Base):
    """Materialized macro report slice (Prompt 45)."""

    __tablename__ = "macro_report_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_type: Mapped[str] = mapped_column(String(16), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MacroSeriesHistoryORM(Base):
    """Week-over-week comparison index (Prompt 45)."""

    __tablename__ = "macro_series_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[Decimal] = mapped_column(nullable=False)
    quality_flag: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("instrument", "period", "as_of", name="macro_series_history_instrument_period_asof_key"),
    )


class MacroCalendarEntryORM(Base):
    """Upcoming macro release schedule (Prompt 49)."""

    __tablename__ = "macro_calendar_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_release_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_covered: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("macro_source_registry.source_id"),
        nullable=False,
    )
    consensus_estimate: Mapped[Decimal | None] = mapped_column(nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "instrument",
            "expected_release_time",
            "source_id",
            name="macro_calendar_entries_instrument_release_source_key",
        ),
    )
