"""
Pydantic v2 schemas for request/response validation.
"""
from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from numbers import Real
from typing import Any, Optional, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.utils.json_safe import finite_float, sanitize_for_json


# ── Base ─────────────────────────────────────────────────────────────────────

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    fingerprint: str | None = None
    user_agent: str | None = None
    webauthn_credential: dict | None = None


class TokenResponse(BaseModel):
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "bearer"
    expires_in: int = 0
    must_change_password: bool = False
    webauthn_required: bool = False
    webauthn_registration_required: bool = False
    pending_approval: bool = False
    email_verification_required: bool = False
    two_factor_required: bool = False
    two_factor_pending_token: str = ""
    two_factor_backup_allowed: bool = False
    two_factor_enrollment_required: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequestIn(BaseModel):
    new_password: str = Field(min_length=12)
    confirm_password: str = Field(min_length=12)

    @model_validator(mode="after")
    def passwords_match(self) -> Self:
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class PasswordChangeConfirmIn(BaseModel):
    new_password: str = Field(min_length=12)
    confirm_password: str = Field(min_length=12)
    code: str | None = Field(default=None, min_length=6, max_length=6)
    token: str | None = None

    @model_validator(mode="after")
    def passwords_match(self) -> Self:
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        if not self.code and not self.token:
            raise ValueError("Confirmation code or token required")
        return self


class RecoverPasswordIn(BaseModel):
    email: EmailStr


class RecoverPasswordOut(BaseModel):
    ok: bool = True
    message: str


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=32)
    new_password: str = Field(min_length=12)
    confirm_password: str = Field(min_length=12)

    @model_validator(mode="after")
    def passwords_match(self) -> Self:
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class VerifyEmailRequestIn(BaseModel):
    email: EmailStr


class VerifyEmailConfirmIn(BaseModel):
    token: str = Field(min_length=32)


class GenericMessageOut(BaseModel):
    ok: bool = True
    message: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    fingerprint: str | None = None
    user_agent: str | None = None
    timezone_mismatch: bool = False
    contact_name: str | None = None
    contact_phone: str | None = None
    jurisdiction: str | None = None
    capital_range: str | None = None
    experience_level: str | None = None
    strategy_interest: str | None = None
    notes: str | None = None
    turnstile_token: str | None = None
    # Two separate ticks on the form: the user agreement + privacy policy, and the
    # consent to personal-data processing (152-ФЗ требует отдельного согласия).
    accept_terms: bool = False
    consent_pd: bool = False
    # Russian mobile number confirmed by SMS (149-FZ art. 10.6).
    phone: str | None = None
    phone_code: str | None = None


class UserOut(BaseSchema):
    id: str
    email: str
    role: str
    is_active: bool
    is_whitelisted: bool
    email_verified: bool = False
    phone_verified: bool = False
    phone_last4: str | None = None
    created_at: datetime
    last_login: Optional[datetime] = None


# ── Maneuver ─────────────────────────────────────────────────────────────────

class ManeuverStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    FILLED = "filled"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"


class StrategyType(str, Enum):
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    GRID = "grid"
    EVENT_DRIVEN = "event_driven"
    TREND_FOLLOWING = "trend_following"
    MACRO = "macro"
    NO_TRADE = "no_trade"


class ManeuverOut(BaseSchema):
    id: str
    rank: int
    ticker: str
    strategy_type: StrategyType
    direction: str
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    exit_zone_low: Optional[float] = None
    exit_zone_high: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    invalidation_level: Optional[float] = None
    risk_percent: float
    position_size_usd: float
    expected_return_low: Optional[float] = None
    expected_return_high: Optional[float] = None
    expected_pnl_low: Optional[float] = None
    expected_pnl_high: Optional[float] = None
    confidence: float
    time_horizon: str
    catalyst: Optional[str] = None
    rationale: Optional[str] = None
    execution_plan: Optional[str] = None
    status: ManeuverStatus
    trading_mode: str
    approved_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    fill_price: Optional[float] = None
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    exit_reason: Optional[str] = None
    created_at: datetime
    closed_at: Optional[datetime] = None

    # ── Live position enrichment (populated by the API for open positions) ──
    # approx_profit:  projected NET P&L (USD) if take-profit is hit, after fees.
    # unrealized_pnl: live NET P&L (USD) if closed now at current_price.
    # time_to_close:  seconds until horizon expires (0 if overdue).
    # current_price:  latest known close for live P&L reference.
    approx_profit: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    time_to_close: Optional[int] = None
    current_price: Optional[float] = None
    horizon_end_at: Optional[str] = Field(
        None,
        description="Absolute UTC ISO timestamp when the maneuver horizon expires.",
    )
    expiry_at: Optional[str] = Field(
        None,
        description="Alias of horizon_end_at for clients that require explicit expiry naming.",
    )
    tp_hit_probability: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Estimated probability of hitting TP before horizon expiry.",
    )
    profit_disclosure: Optional[str] = None
    horizon_expired: Optional[bool] = None

    # Signal presentation (spec A.6)
    signal_meta: Optional[dict] = None
    regime_context: Optional[str] = None
    key_drivers: Optional[list[dict]] = None
    risk_flags: Optional[list[str]] = None
    suggested_position_pct: Optional[float] = None
    # Ticker book Average Buy (optional enrichment)
    avg_entry_price: Optional[float] = None

    @model_validator(mode="after")
    def _sanitize_non_finite_floats(self) -> Self:
        for name in self.model_fields:
            val = getattr(self, name)
            if isinstance(val, Real) and not isinstance(val, bool):
                coerced = finite_float(val)
                if coerced is None and val is not None:
                    object.__setattr__(self, name, None)
                elif coerced is not None and coerced != val:
                    object.__setattr__(self, name, coerced)
        if self.stop_loss is None:
            inv = finite_float(self.invalidation_level)
            if inv is not None:
                object.__setattr__(self, "stop_loss", inv)
        if self.take_profit is None:
            high = finite_float(self.exit_zone_high)
            low = finite_float(self.exit_zone_low)
            tp = None
            if high is not None and low is not None:
                tp = (high + low) / 2.0
            else:
                tp = high or low
            if tp is not None:
                object.__setattr__(self, "take_profit", tp)
        return self

    def to_text(self) -> str:
        """Human-readable single maneuver summary."""
        if self.strategy_type == StrategyType.NO_TRADE:
            return (
                f"{self.rank} — НЕТ СДЕЛКИ. "
                f"Причина: {self.rationale or 'Недостаточно уверенности'}. "
                f"Тикер: {self.ticker}."
            )
        entry = f"{self.entry_zone_low:.2f}–{self.entry_zone_high:.2f}" if self.entry_zone_low else "рыночная цена"
        ret_range = (
            f"{self.expected_return_low:.1f}%–{self.expected_return_high:.1f}%"
            if self.expected_return_low is not None else "N/A"
        )
        pnl_range = (
            f"${self.expected_pnl_low:,.0f}–${self.expected_pnl_high:,.0f}"
            if self.expected_pnl_low is not None else "N/A"
        )
        return (
            f"{self.rank} — {self.ticker} ({self.strategy_type.value}, {self.direction}). "
            f"Вход: {entry}. Горизонт: {self.time_horizon}. "
            f"Риск: {self.risk_percent:.1f}%. Сумма: ${self.position_size_usd:,.0f}. "
            f"Ожидаемый доход: {ret_range} ({pnl_range}). "
            f"Уверенность: {self.confidence:.0%}. "
            f"Катализатор: {self.catalyst or '—'}."
        )


class TickerBookOut(BaseSchema):
    ticker: str
    avg_entry: Optional[float] = None
    avg_long: Optional[float] = None
    avg_short: Optional[float] = None
    qty: float = 0.0
    qty_long: float = 0.0
    qty_short: float = 0.0
    exposure_usd: float = 0.0
    long_usd: float = 0.0
    short_usd: float = 0.0
    open_legs: int = 0
    net_side: str = "flat"
    mark_price: Optional[float] = None
    breakeven: Optional[float] = None
    unrealized_usd: Optional[float] = None
    unrealized_pct: Optional[float] = None
    strategy_low: Optional[float] = None
    strategy_high: Optional[float] = None
    risk_low: Optional[float] = None
    risk_high: Optional[float] = None
    avg_in_strategy_zone: Optional[bool] = None
    zone_edge_pct: Optional[float] = None
    legs: list[dict] = Field(default_factory=list)
    markers: list[dict] = Field(default_factory=list)
    pnl_if_flat_hint: Optional[str] = None


class ManeuverReportOut(BaseSchema):
    id: str
    created_at: datetime
    watchlist: list[str]
    pipeline_run_id: str
    text_summary: Optional[str] = None
    regime: Optional[str] = None
    market_context: dict[str, Any] = {}
    status: str
    maneuvers: list[ManeuverOut] = []

    @field_validator("market_context", mode="before")
    @classmethod
    def _sanitize_market_context(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return {}
        return sanitize_for_json(value)

    def to_full_text(self) -> str:
        """Full human-readable 10-maneuver report."""
        lines = [
            f"Предоставлено {len(self.maneuvers)} инвестиционных маневров.",
            f"Режим рынка: {self.regime or 'N/A'}",
            f"Дата: {self.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
        ]
        for m in self.maneuvers:
            lines.append(m.to_text())
        return "\n".join(lines)


class ManeuverApprovalRequest(BaseModel):
    maneuver_id: str
    action: str = Field(pattern="^(approve|reject)$")
    note: Optional[str] = None
    time_horizon: Optional[str] = Field(
        None,
        max_length=50,
        description="User-selected position duration, e.g. '6 hours' or '5 days'.",
    )
    expiry_at: Optional[datetime] = Field(
        None,
        description="Optional exact UTC/local expiry timestamp; takes precedence over duration.",
    )
    trading_mode: Optional[str] = Field(
        None,
        pattern="^(paper|live)$",
        description="Mode chosen in the header at approval time. Live is checked on the server.",
    )


class ManeuverCancelRequest(BaseModel):
    note: Optional[str] = None
    reason: Optional[str] = None


class ManeuverCancelOut(BaseModel):
    maneuver_id: str
    ticker: str
    status_before: str
    status_after: str
    action: str
    size_usd: float
    realized_pnl: Optional[float] = None
    message: str = ""


class DealIntentCancelRequest(BaseModel):
    note: Optional[str] = None
    reason: Optional[str] = None


class DealIntentCancelOut(BaseModel):
    deal_intent_id: str
    status_before: str
    status_after: str
    message: str = ""


class DealIntentApprovalRequest(BaseModel):
    action: str = Field(default="approve", pattern="^(approve|reject)$")
    note: Optional[str] = None
    reason: Optional[str] = None


class DealIntentApprovalOut(BaseModel):
    deal_intent_id: str
    status_before: str
    status_after: str
    action: str
    message: str = ""


class DealIntentEditRequest(BaseModel):
    target_price: Optional[float] = Field(None, gt=0)
    direction: Optional[str] = Field(None, pattern="^(long|short)$")
    required_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    max_slippage_bps: Optional[int] = Field(None, ge=0)
    max_spread_bps: Optional[int] = Field(None, ge=0)
    time_in_force: Optional[str] = Field(
        None,
        pattern="^(day|gtc|ioc|fok|gtd)$",
    )
    trigger_type: Optional[str] = Field(
        None,
        pattern="^(market|limit|stop|condition)$",
    )
    approval_threshold: Optional[float] = Field(None, ge=0)
    risk_tag: Optional[str] = Field(
        None,
        pattern="^(low|medium|high|event_risk)$",
    )
    hedge_attachment_id: Optional[str] = Field(None, max_length=36)
    exit_logic: Optional[dict[str, Any]] = None
    note: Optional[str] = None


class ManeuverEditRequest(BaseModel):
    size_usd: Optional[float] = Field(None, gt=0)
    entry_price: Optional[float] = Field(None, gt=0)
    stop_loss: Optional[float] = Field(None, gt=0)
    take_profit: Optional[float] = Field(None, gt=0)
    time_horizon: Optional[str] = Field(None, max_length=50)
    expiry_at: Optional[datetime] = None
    note: Optional[str] = None


# ── Pipeline ─────────────────────────────────────────────────────────────────

class PipelineRunRequest(BaseModel):
    watchlist: Optional[list[str]] = None
    force_refresh: bool = False
    portfolio_size: Optional[float] = Field(None, gt=0)

    @field_validator("watchlist")
    @classmethod
    def normalize_tickers(cls, v: list[str] | None) -> list[str] | None:
        if v:
            from app.services.market_data.moex_spot import normalize_watchlist_ticker

            return [normalize_watchlist_ticker(t) for t in v if t.strip()]
        return v


class PipelineRunResponse(BaseModel):
    run_id: str
    task_id: Optional[str] = None
    status: str
    message: str
    report_id: Optional[str] = None
    eta_seconds: Optional[int] = None
    tradeable_count: Optional[int] = None
    maneuver_slots: Optional[int] = None


class UserSettingsOut(BaseModel):
    portfolio_size: float
    max_risk_per_trade_pct: float
    confidence_threshold: float
    daily_max_loss_pct: float
    default_watchlist: list[str] = []
    paper_trading_enabled: bool = True
    live_trading_enabled: bool = False
    tokenized_equity_provider: str = "bybit"
    cap_max_usd: float = Field(
        0.0,
        description="Account total (all money on trading accounts); cap cannot exceed this",
    )


class UserSettingsUpdate(BaseModel):
    portfolio_size: Optional[float] = Field(None, gt=0)
    max_risk_per_trade_pct: Optional[float] = Field(None, gt=0, le=10)
    confidence_threshold: Optional[float] = Field(None, gt=0, lt=1)
    daily_max_loss_pct: Optional[float] = Field(None, gt=0, le=50)
    default_watchlist: Optional[list[str]] = None
    tokenized_equity_provider: Optional[str] = None

    @field_validator("default_watchlist")
    @classmethod
    def uppercase_tickers(cls, v: list[str] | None) -> list[str] | None:
        if v:
            return [t.strip().upper() for t in v if t.strip()]
        return v


# ── Market Data ──────────────────────────────────────────────────────────────

class OHLCVBarOut(BaseSchema):
    ticker: str
    timestamp: datetime
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: Optional[float] = None

    @model_validator(mode="after")
    def _sanitize_non_finite_floats(self) -> Self:
        for name in self.model_fields:
            val = getattr(self, name)
            if isinstance(val, Real) and not isinstance(val, bool) and not math.isfinite(float(val)):
                object.__setattr__(self, name, None if name == "vwap" else 0.0)
        return self


class MarketQuote(BaseModel):
    ticker: str
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[float] = None
    change_pct: Optional[float] = None
    timestamp: datetime


# ── News ─────────────────────────────────────────────────────────────────────

class NewsArticleOut(BaseSchema):
    id: str
    title: str
    description: Optional[str] = None
    title_ru: Optional[str] = None
    summary_ru: Optional[str] = None
    is_machine_translated: bool = False
    url: str
    source: str
    published_at: datetime
    sentiment_score: Optional[float] = None
    sentiment_label: Optional[str] = None
    tickers_mentioned: list[str] = []
    relevance_score: float = 0.0

    @model_validator(mode="after")
    def _only_real_mentions(self) -> Self:
        from app.services.news.client import clean_mentions

        text = " ".join(x for x in (self.title, self.description, self.title_ru, self.summary_ru) if x)
        self.tickers_mentioned = clean_mentions(text, self.tickers_mentioned)
        return self


# ── Backtest ─────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    strategy: str
    ticker: str
    start_date: str  # ISO date
    end_date: str    # ISO date
    initial_capital: float = Field(default=100_000.0, gt=0)
    parameters: dict[str, Any] = {}


class BacktestResultOut(BaseSchema):
    id: str
    strategy: str
    ticker: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: Optional[float] = None
    total_return_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    total_trades: Optional[int] = None
    win_rate: Optional[float] = None
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    metrics: dict[str, Any] = {}


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLogOut(BaseSchema):
    id: str
    timestamp: datetime
    user_id: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: dict[str, Any] = {}
    ip_address: Optional[str] = None
    success: bool
    error: Optional[str] = None


# ── Watchlist ─────────────────────────────────────────────────────────────────

class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    tickers: list[str] = Field(min_length=1)

    @field_validator("tickers")
    @classmethod
    def uppercase_tickers(cls, v: list[str]) -> list[str]:
        return [t.strip().upper() for t in v if t.strip()]


class WatchlistOut(BaseSchema):
    id: str
    name: str
    tickers: list[str]
    is_default: bool
    created_at: datetime


# ── System ───────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Public probe: connectivity only, no build or environment fingerprint."""

    status: str = "ok"
    db: str = "unknown"
    redis: str = "unknown"
    trading_mode: str


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int
    meta: Optional[dict[str, Any]] = None

    @field_validator("meta", mode="before")
    @classmethod
    def _sanitize_meta(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, dict):
            return None
        return sanitize_for_json(value)
