"""
ORM models for the Apex Intel platform.
All timestamps stored in UTC.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


# ── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, PyEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class ManeuverStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    FILLED = "filled"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"


class StrategyType(str, PyEnum):
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    GRID = "grid"
    EVENT_DRIVEN = "event_driven"
    TREND_FOLLOWING = "trend_following"
    MACRO = "macro"
    NO_TRADE = "no_trade"


class TradingMode(str, PyEnum):
    PAPER = "paper"
    LIVE = "live"


class SignalDirection(str, PyEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


# ── User ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(20), default=UserRole.VIEWER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_whitelisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Sign-in is tied to a verified Russian mobile number (149-FZ art. 10.6, 13.55 KoAP).
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    phone_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Google Authenticator / TOTP (secret encrypted at rest via field_encryption)
    two_factor_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_factor_backup_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    two_factor_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    two_factor_disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    maneuver_reports = relationship("ManeuverReport", back_populates="created_by_user")
    audit_logs = relationship("AuditLog", back_populates="user")

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class LegalAcceptance(Base):
    """One consent a person gave: which text, which version, when, from where."""

    __tablename__ = "legal_acceptances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    document_code: Mapped[str] = mapped_column(String(40), nullable=False)
    document_version: Mapped[str] = mapped_column(String(20), nullable=False)
    document_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Watchlist ────────────────────────────────────────────────────────────────

class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    tickers: Mapped[list[str]] = mapped_column(JSON, default=list)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ── Market OHLCV ─────────────────────────────────────────────────────────────

class OHLCVBar(Base):
    """TimescaleDB hypertable for OHLCV bars."""
    __tablename__ = "ohlcv_bars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)  # 1m, 5m, 1h, 1d
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="alpaca")

    __table_args__ = (
        UniqueConstraint("ticker", "timestamp", "timeframe", name="uq_ohlcv_bar"),
        Index("ix_ohlcv_ticker_ts", "ticker", "timestamp"),
    )


# ── News ─────────────────────────────────────────────────────────────────────

class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)   # -1 to 1
    sentiment_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tickers_mentioned: Mapped[list[str]] = mapped_column(JSON, default=list)
    extracted_events: Mapped[list[dict]] = mapped_column(JSON, default=list)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (Index("ix_news_published", "published_at"),)


class ForecastSnapshot(Base):
    """Persisted daily forecast output per instrument (Celery beat job)."""

    __tablename__ = "forecast_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    instrument_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    snapshot_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="live", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_forecast_snapshots_symbol_date", "symbol", "snapshot_date"),
        Index("ix_forecast_snapshots_symbol_date_source", "symbol", "snapshot_date", "source"),
    )


class ForecastSnapshotResolution(Base):
    """Append-only resolution of a forecast snapshot vs realized OHLCV."""

    __tablename__ = "forecast_snapshot_resolutions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    snapshot_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    predicted_direction: Mapped[int] = mapped_column(Integer, nullable=False)
    realized_return: Mapped[float] = mapped_column(Float, nullable=False)
    direction_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_forecast_resolutions_symbol_resolved", "symbol", "resolved_at"),
    )


# ── Macro Event ───────────────────────────────────────────────────────────────

class MacroEvent(Base):
    """Economic / geopolitical macro events affecting markets."""
    __tablename__ = "macro_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(10), default="US")
    impact: Mapped[str] = mapped_column(String(20), default="medium")  # low/medium/high
    source: Mapped[str] = mapped_column(String(100), default="system")
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    market_effect: Mapped[float] = mapped_column(Float, default=0.0)  # -1 to 1
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    tickers_affected: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_macro_event_date", "event_date"),)


# ── Market Signal ─────────────────────────────────────────────────────────────

class MarketSignal(Base):
    __tablename__ = "market_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[SignalDirection] = mapped_column(String(10), nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False)  # 0–1
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0–1
    features: Mapped[dict] = mapped_column(JSON, default=dict)   # feature values
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    price_at_signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Maneuver Report ───────────────────────────────────────────────────────────

class ManeuverReport(Base):
    """One pipeline run = one report containing exactly 10 maneuvers."""
    __tablename__ = "maneuver_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    watchlist: Mapped[list[str]] = mapped_column(JSON, default=list)
    pipeline_run_id: Mapped[str] = mapped_column(String(36), default=new_uuid)
    text_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    regime: Mapped[str | None] = mapped_column(String(50), nullable=True)
    market_context: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="complete")

    created_by_user = relationship("User", back_populates="maneuver_reports")
    maneuvers = relationship(
        "Maneuver", back_populates="report", order_by="Maneuver.rank"
    )


# ── Maneuver ──────────────────────────────────────────────────────────────────

class Maneuver(Base):
    """Single investment maneuver (1 of 10 per report)."""
    __tablename__ = "maneuvers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    report_id: Mapped[str] = mapped_column(ForeignKey("maneuver_reports.id"), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–10
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_type: Mapped[StrategyType] = mapped_column(String(30), nullable=False)
    direction: Mapped[SignalDirection] = mapped_column(String(10), nullable=False)

    # Price levels
    entry_zone_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_zone_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_zone_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_zone_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    invalidation_level: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Risk / Return
    risk_percent: Mapped[float] = mapped_column(Float, nullable=False)  # % of portfolio
    position_size_usd: Mapped[float] = mapped_column(Float, nullable=False)
    expected_return_low: Mapped[float | None] = mapped_column(Float, nullable=True)  # %
    expected_return_high: Mapped[float | None] = mapped_column(Float, nullable=True)  # %
    expected_pnl_low: Mapped[float | None] = mapped_column(Float, nullable=True)   # USD
    expected_pnl_high: Mapped[float | None] = mapped_column(Float, nullable=True)  # USD
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0–1

    # Metadata
    time_horizon: Mapped[str] = mapped_column(String(50), nullable=False)  # "1-3 days"
    catalyst: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_signals: Mapped[list[str]] = mapped_column(JSON, default=list)  # signal IDs
    source_news: Mapped[list[str]] = mapped_column(JSON, default=list)     # article IDs
    signal_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Lifecycle
    status: Mapped[ManeuverStatus] = mapped_column(String(20), default=ManeuverStatus.PENDING)
    trading_mode: Mapped[TradingMode] = mapped_column(String(10), default=TradingMode.PAPER)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Position audit metadata (closed positions)
    exit_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    factor_exposures_at_entry: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    peak_unrealized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_generated_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime_at_entry: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sector_at_entry: Mapped[str | None] = mapped_column(String(80), nullable=True)

    report = relationship("ManeuverReport", back_populates="maneuvers")

    __table_args__ = (
        UniqueConstraint("report_id", "rank", name="uq_maneuver_rank"),
        Index("ix_maneuver_ticker_status", "ticker", "status"),
    )


class PositionAudit(Base):
    """Async position audit report for a user (100 expiration closes)."""
    __tablename__ = "position_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    required_count: Mapped[int] = mapped_column(Integer, default=100)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    report_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    user_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ── Execution Order ───────────────────────────────────────────────────────────

class ExecutionOrder(Base):
    __tablename__ = "execution_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    maneuver_id: Mapped[str] = mapped_column(ForeignKey("maneuvers.id"), nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # buy / sell
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)  # market/limit
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    trading_mode: Mapped[TradingMode] = mapped_column(String(10), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fill_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict)

    maneuver = relationship("Maneuver")


# ── Manual Orders (operator ticket module) ────────────────────────────────────

class ManualOrder(Base):
    __tablename__ = "manual_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_in_force: Mapped[str] = mapped_column(String(10), default="gtc")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    bracket_stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    bracket_take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    oco_sibling_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    maneuver_id: Mapped[str | None] = mapped_column(ForeignKey("maneuvers.id"), nullable=True)
    sibling_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fill_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_fees_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConditionalOrderWatch(Base):
    __tablename__ = "conditional_order_watches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    manual_order_id: Mapped[str] = mapped_column(ForeignKey("manual_orders.id"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trail_distance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="watching", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Backtest Run ──────────────────────────────────────────────────────────────

class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    strategy: Mapped[str] = mapped_column(String(100), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False)
    final_capital: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    equity_curve: Mapped[list] = mapped_column(JSON, default=list)
    trade_log: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", back_populates="audit_logs")

    __table_args__ = (Index("ix_audit_ts_action", "timestamp", "action"),)


class TradingPlacementAudit(Base):
    """Immutable log of order/maneuver placement requests (who, when, symbol, side, broker mode)."""

    __tablename__ = "trading_placement_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    broker_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    __table_args__ = (Index("ix_trading_placement_ts_symbol", "timestamp", "symbol"),)


class WatchlistAlertRule(Base):
    """User-defined threshold alerts for watchlisted symbols (blueprint §8)."""

    __tablename__ = "watchlist_alert_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False, default="ml_confidence")
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False, default="above")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ── Trading Core: Accounts & Strategies ─────────────────────────────────────


class TradingAccount(Base):
    __tablename__ = "trading_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    mode: Mapped[TradingMode] = mapped_column(
        String(10), default=TradingMode.PAPER, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    strategies: Mapped[list["TradingStrategy"]] = relationship(
        "TradingStrategy",
        back_populates="account",
        cascade="all, delete-orphan",
    )



class TradingStrategy(Base):
    __tablename__ = "trading_strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trading_accounts.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    account: Mapped["TradingAccount"] = relationship(
        "TradingAccount",
        back_populates="strategies",
    )


# ── Trading Core: Trades ─────────────────────────────────────────────────────


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)

    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("trading_accounts.id"),
        nullable=False,
        index=True,
    )
    strategy_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("trading_strategies.id"),
        nullable=True,
        index=True,
    )

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    venue: Mapped[str] = mapped_column(String(50), nullable=False)

    side: Mapped[str] = mapped_column(String(10), nullable=False)  # "buy" / "sell"
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        index=True,
    )

    order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    account: Mapped["TradingAccount"] = relationship("TradingAccount")
    strategy: Mapped["TradingStrategy | None"] = relationship("TradingStrategy")