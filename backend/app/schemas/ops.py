"""Read-only ops / pilot status schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any


class PilotLimitsOut(BaseModel):
    enabled: bool = False
    max_notional_per_order: float = 0.0
    max_daily_loss: float = 0.0
    max_orders_per_session: int = 0
    source: str = "static"


class PilotVenueOut(BaseModel):
    enabled: bool = False
    allowed_venue: str = ""
    allowed_symbols: list[str] = Field(default_factory=list)
    source: str = "static"


class AuditPathsOut(BaseModel):
    stop_drill: str
    signoff: str
    pilot_root: str


class DocsLinkOut(BaseModel):
    name: str
    path: str


class GridBotTestCountsOut(BaseModel):
    gate_label: str
    command: str
    expected_count: int = 994


class KillSwitchDrillOut(BaseModel):
    data_dir: str
    exists: bool = False
    audit_file: str | None = None
    passed: bool | None = None
    session_id: str | None = None
    drill_id: str | None = None
    ts_utc: str | None = None
    drill_command: str
    docs_path: str


class VenueConnectivityOut(BaseModel):
    venue: str
    configured: bool = False
    mode: str = "pending"
    detail: str = ""


class LastPipelineRunOut(BaseModel):
    run_id: str | None = None
    report_id: str | None = None
    status: str = "unknown"
    triggered_by: str | None = None
    completed_at: str | None = None
    watchlist_count: int = 0


class GridBotTickStatusOut(BaseModel):
    enabled: bool = True
    schedule: str = "every minute (Celery beat)"
    active_bots: int = 0
    last_tick_at: str | None = None
    last_tick_status: str | None = None
    last_updated_bots: int = 0
    last_fills: int = 0


class ForecastRefreshStatusOut(BaseModel):
    enabled: bool = True
    schedule: str = "daily 05:00 UTC (Celery beat)"
    last_refresh_at: str | None = None
    last_status: str | None = None
    symbols_saved: int = 0
    watchlist_size: int = 0


class PilotStatusOut(BaseModel):
    phase4_bundle_command: str
    pilot_limits: PilotLimitsOut
    pilot_venue: PilotVenueOut
    venue_connectivity: list[VenueConnectivityOut] = Field(default_factory=list)
    app_trading_mode: str = "paper"
    paper_trading_enabled: bool = True
    live_trading_enabled: bool = False
    paper_capabilities: dict[str, Any] = Field(default_factory=dict)
    last_pipeline_run: LastPipelineRunOut = Field(default_factory=LastPipelineRunOut)
    grid_bot_tick: GridBotTickStatusOut = Field(default_factory=GridBotTickStatusOut)
    forecast_refresh: ForecastRefreshStatusOut = Field(default_factory=ForecastRefreshStatusOut)
    audit_paths: AuditPathsOut
    last_drill_files: list[str] = Field(default_factory=list)
    grid_bot_test_counts: GridBotTestCountsOut
    docs_links: list[DocsLinkOut] = Field(default_factory=list)
    kill_switch_drill: KillSwitchDrillOut


class StopDrillRunOut(BaseModel):
    """Result of running the staging stop drill via the ops API."""

    passed: bool = False
    session_id: str
    reason: str = ""
    data_dir: str
    audit_file: str | None = None
    staging: bool = True
    production_mutation: bool = False
    report: dict = Field(default_factory=dict)
    error: str | None = None


class LlmStatusOut(BaseModel):
    """AITunnel / LLM availability for UI indicators (navbar, not full-width banners)."""

    available: bool
    message_ru: str
    reason: str | None = None
    balance_rub: float | None = None


class MarketAnalysisRunOut(BaseModel):
    """Result of triggering the market-intelligence pipeline via the ops API."""

    run_id: str
    task_id: str | None = None
    status: str = "queued"
    message: str = ""
    watchlist: list[str] = Field(default_factory=list)


class ClosedPositionOut(BaseModel):
    """One position affected by a flatten / close-all operation."""

    id: str
    ticker: str
    direction: str
    status_before: str
    action: str = Field(..., description="closed | cancelled")
    size_usd: float = 0.0
    realized_pnl: float | None = None
    close_price: float | None = None


class CloseAllPositionsOut(BaseModel):
    """Result of flattening the paper book via the ops API."""

    mode: str = "paper"
    closed_count: int = 0
    cancelled_count: int = 0
    realized_pnl_total: float = 0.0
    freed_exposure_usd: float = 0.0
    message: str = ""
    positions: list[ClosedPositionOut] = Field(default_factory=list)
