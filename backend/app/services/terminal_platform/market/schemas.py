"""
Stable response schemas for Terminal Market aggregate APIs.

Contract (frontend-facing under /api/v1/terminal/):
  GET /snapshot, /indices, /pulse, /market-hours, /tape,
  GET /watchlist, /portfolio, /quant/factors

Hard rule: never invent 0.00 for a failed quote — use null + status/reason, or omit the row.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class IndexQuoteRow(BaseModel):
    symbol: str
    name: Optional[str] = None
    api_symbol: Optional[str] = None
    price: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    week_change_pct: Optional[float] = None
    month_change_pct: Optional[float] = None
    session_status: Optional[str] = None  # open | closed | pre | post | unknown
    provider: Optional[str] = None
    as_of: Optional[str] = None
    currency: Optional[str] = None
    status: Literal["ok", "no_data"] = "ok"
    reason: Optional[str] = None


class PerformanceRow(BaseModel):
    label: str
    period: str
    value: Optional[float] = None
    unit: Literal["pct", "level", "bps"] = "pct"
    status: Literal["ok", "no_data"] = "ok"
    reason: Optional[str] = None


class BreadthRow(BaseModel):
    exchange: str
    advancers: Optional[int] = None
    decliners: Optional[int] = None
    unchanged: Optional[int] = None
    status: Literal["ok", "no_data", "estimated"] = "ok"
    reason: Optional[str] = None


class MoverRow(BaseModel):
    symbol: str
    change_pct: Optional[float] = None
    price: Optional[float] = None
    volume: Optional[float] = None
    name: Optional[str] = None


class GlobalSnapshotItem(BaseModel):
    key: str  # VIX | US10Y | DXY | GOLD | OIL | BTC
    symbol: str
    label: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    provider: Optional[str] = None
    status: Literal["ok", "no_data"] = "ok"
    reason: Optional[str] = None


class MarketPulseBlock(BaseModel):
    fear_greed: Optional[int] = None
    label: Optional[str] = None
    fear_greed_components: dict[str, Any] = Field(default_factory=dict)
    breadth: list[BreadthRow] = Field(default_factory=list)
    gainers: list[MoverRow] = Field(default_factory=list)
    losers: list[MoverRow] = Field(default_factory=list)
    global_snapshot: list[GlobalSnapshotItem] = Field(default_factory=list)
    volatility_regime: Optional[str] = None  # calm | moderate | elevated | extreme


class MarketHoursRow(BaseModel):
    exchange: str
    name: str
    timezone: str
    status: Literal["open", "closed", "pre", "post", "holiday"]
    local_time: str
    next_event: Optional[str] = None
    next_event_at: Optional[str] = None
    regular_hours: Optional[str] = None


class TapeItem(BaseModel):
    kind: Literal["quote", "mover", "vix", "headline", "hours"]
    symbol: Optional[str] = None
    text: str
    change_pct: Optional[float] = None
    price: Optional[float] = None
    ts: Optional[str] = None


class WatchlistEnrichedRow(BaseModel):
    symbol: str
    display: Optional[str] = None
    category: Optional[str] = None
    last: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    day_change_pct: Optional[float] = None
    week_change_pct: Optional[float] = None
    month_change_pct: Optional[float] = None
    ytd_change_pct: Optional[float] = None
    volume: Optional[float] = None
    atr: Optional[float] = None
    vol_atr: Optional[float] = None
    trend: Optional[str] = None
    regime: Optional[str] = None
    risk_score: Optional[float] = None
    sector: Optional[str] = None
    session: Optional[str] = None
    live_delayed: Optional[str] = None  # live | delayed | eod | forex | unknown
    provider: Optional[str] = None
    as_of: Optional[str] = None
    status: Literal["ok", "no_data"] = "ok"
    reason: Optional[str] = None
    data_only: Optional[bool] = None
    execution_enabled: Optional[bool] = None
    feed_label_ru: Optional[str] = None
    currency: Optional[str] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    routing_class: Optional[str] = None
    show_volume: Optional[bool] = None


class PortfolioPositionRow(BaseModel):
    symbol: str
    qty: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    weight_pct: Optional[float] = None


class PortfolioSummaryBlock(BaseModel):
    has_positions: bool = False
    message: Optional[str] = None
    total_usd: Optional[float] = None
    trading_usd: Optional[float] = None
    balance_usd: Optional[float] = None
    day_pnl_usd: Optional[float] = None
    total_pnl_usd: Optional[float] = None
    unrealized_pnl_usd: Optional[float] = None
    realized_pnl_usd: Optional[float] = None
    exposure_pct: Optional[float] = None
    drawdown_pct: Optional[float] = None
    concentration_pct: Optional[float] = None
    open_positions: int = 0
    positions: list[PortfolioPositionRow] = Field(default_factory=list)
    mode: Optional[str] = None
    source: Optional[str] = None
    as_of: Optional[str] = None


class QuantFactorRow(BaseModel):
    name: str
    weight: Optional[float] = None
    contribution: Optional[float] = None
    source: str
    freshness: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    why: str


class DataCoverageRow(BaseModel):
    layer: str
    surfaced: bool
    detail: str
    reason_if_not: Optional[str] = None


class NewsTapeRow(BaseModel):
    id: str
    headline: str
    source: str
    published_at: str
    url: Optional[str] = None
    summary: Optional[str] = None


class CalendarTapeRow(BaseModel):
    id: str
    title: str
    when: str
    region: Optional[str] = None
    importance: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    previous: Optional[str] = None
    forecast: Optional[str] = None


class RiskHighBetaRow(BaseModel):
    symbol: str
    price: Optional[float] = None
    beta: Optional[float] = None
    change_pct: Optional[float] = None
    note: Optional[str] = None


class RiskSummaryBlock(BaseModel):
    score: Optional[float] = None
    label: Optional[str] = None
    var_pct: Optional[float] = None
    high_beta: list[RiskHighBetaRow] = Field(default_factory=list)
    reason: Optional[str] = None


class ChartPoint(BaseModel):
    t: int  # unix ms
    v: float


class ChartSeries(BaseModel):
    symbol: str
    points: list[ChartPoint] = Field(default_factory=list)
    provider: Optional[str] = None
    source: Literal["live", "empty"] = "empty"
    reason: Optional[str] = None


class FeedFreshnessBlock(BaseModel):
    last_refreshed_at: str
    newest_item_at: Optional[str] = None
    is_stale: bool = False
    age_sec: Optional[float] = None
    stale_after_sec: int = 3600
    expected_interval_sec: int = 1800
    item_count: int = 0
    from_cache: bool = False


class TerminalMarketSnapshot(BaseModel):
    """Single payload for the Market view — Fincept-class density without fake zeros."""

    as_of: str
    source: Literal["live", "partial", "empty"] = "live"
    indices: list[IndexQuoteRow] = Field(default_factory=list)
    performance: list[PerformanceRow] = Field(default_factory=list)
    pulse: MarketPulseBlock = Field(default_factory=MarketPulseBlock)
    watchlist_enriched: list[WatchlistEnrichedRow] = Field(default_factory=list)
    portfolio_summary: PortfolioSummaryBlock = Field(default_factory=PortfolioSummaryBlock)
    market_hours: list[MarketHoursRow] = Field(default_factory=list)
    tape_items: list[TapeItem] = Field(default_factory=list)
    news: list[NewsTapeRow] = Field(default_factory=list)
    calendar: list[CalendarTapeRow] = Field(default_factory=list)
    risk: RiskSummaryBlock = Field(default_factory=RiskSummaryBlock)
    quant_factors: list[QuantFactorRow] = Field(default_factory=list)
    data_coverage: list[DataCoverageRow] = Field(default_factory=list)
    chart: Optional[ChartSeries] = None
    data_health: Optional[dict[str, Any]] = None
    news_freshness: Optional[FeedFreshnessBlock] = None
    calendar_freshness: Optional[FeedFreshnessBlock] = None
    meta: dict[str, Any] = Field(default_factory=dict)
