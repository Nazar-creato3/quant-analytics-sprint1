"""Robot Core ORM: lots, plans, fills, sessions, funding, fees, governance, market edge."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import new_uuid, utcnow
from app.db.session import Base


class PositionLot(Base):
    """Atomic inventory lot — truth for Average Buy / FIFO realized P&L."""

    __tablename__ = "position_lots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # long | short
    qty_open: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    qty_initial: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    fee_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="maneuver")
    maneuver_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("maneuvers.id"), nullable=True)
    robot_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open|closed
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_position_lots_user_ticker_status", "user_id", "ticker", "status"),
    )


class LotCloseEvent(Base):
    """FIFO reduce/close audit row."""

    __tablename__ = "lot_close_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("position_lots.id"), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fee_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    maneuver_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RobotPlan(Base):
    """Executable level plan attached to a strategy session / maneuver."""

    __tablename__ = "robot_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    maneuver_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("maneuvers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # active | paused | completed | cancelled
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="long")
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="paper")  # paper|live
    levels: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    kill_switch_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_equity_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # plan_type: custom | grid | dca | freqtrade
    plan_type: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    plan_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # live capabilities snapshot (honest matrix)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    is_legacy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_robot_plans_user_status", "user_id", "status"),
        Index("ix_robot_plans_maneuver", "maneuver_id"),
    )


class RobotLevelFill(Base):
    """Idempotent fill ledger for robot level actions (add/tp/sl/trail)."""

    __tablename__ = "robot_level_fills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("robot_plans.id"), nullable=False, index=True)
    level_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # add|tp|sl|trail|entry
    celery_task_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    client_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fee_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    liquidity: Mapped[str] = mapped_column(String(8), nullable=False, default="taker")  # maker|taker
    maneuver_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "plan_id", "level_id", "action", "celery_task_id",
            name="uq_robot_level_fill_idem",
        ),
        Index("ix_robot_level_fills_client_order", "client_order_id", unique=True),
    )


class StrategySession(Base):
    """Explicit strategy session: entry → adds → scales → flat."""

    __tablename__ = "strategy_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    robot_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # active | paused | closed | overridden
    entry_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    override_log: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    total_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_funding: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_strategy_sessions_user_status", "user_id", "status"),
    )


class FundingEvent(Base):
    """Venue funding payment accrued to a lot / plan."""

    __tablename__ = "funding_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    lot_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    venue: Mapped[str] = mapped_column(String(32), nullable=False, default="paper")
    rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="USD")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_funding_events_user_ticker", "user_id", "ticker"),
    )


class VenueFee(Base):
    """Cached maker/taker fee rates per venue/symbol."""

    __tablename__ = "venue_fees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, default="*")
    maker_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0002)
    taker_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0005)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("venue", "symbol", name="uq_venue_fees_venue_symbol"),
    )


class GovernanceLog(Base):
    """Human intervention / multi-sig flatten audit."""

    __tablename__ = "governance_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # flatten|pause|override_kill
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # pending | approved | rejected | executed
    initiated_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    affected_plans: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PortfolioRiskState(Base):
    """Portfolio-level kill / exposure state per user."""

    __tablename__ = "portfolio_risk_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, unique=True)
    equity_start_of_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    equity_start_of_month: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_anchor_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    month_anchor: Mapped[str | None] = mapped_column(String(7), nullable=True)
    kill_switch_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kill_switch_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    day_limit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    month_limit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=15.0)
    max_exposure_symbol_pct: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    max_exposure_venue_pct: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    max_correlation: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class OrderbookSnapshot(Base):
    """L2 order book snapshot for regime / research."""

    __tablename__ = "orderbook_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    ticker: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    venue: Mapped[str] = mapped_column(String(32), nullable=False, default="paper")
    bids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    asks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_orderbook_snapshots_ticker_ts", "ticker", "captured_at"),
    )


class TapeEvent(Base):
    """Recent trade tape print."""

    __tablename__ = "tape_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    ticker: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    venue: Mapped[str] = mapped_column(String(32), nullable=False, default="paper")
    price: Mapped[float] = mapped_column(Float, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="buy")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_tape_events_ticker_ts", "ticker", "occurred_at"),
    )
