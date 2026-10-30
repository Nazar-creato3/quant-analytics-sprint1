"""Portfolio metrics schemas for NavBar / cockpit."""
from __future__ import annotations

import math
from numbers import Real
from typing import Self

from pydantic import BaseModel, Field, model_validator


class PortfolioMetricsOut(BaseModel):
    """Live portfolio capital breakdown: TRD (in trades), BLNC (free cash), SUM (total)."""

    trading_usd: float = Field(..., description="Capital in open positions / active trades (TRD)")
    balance_usd: float = Field(..., description="Free / untouched cash (BLNC)")
    total_usd: float = Field(..., description="Total capital: TRD + BLNC (SUM)")
    currency: str = "USD"
    mode: str = Field(..., description="paper | live")
    source: str = Field(..., description="alpaca | internal")
    open_maneuvers: int = 0
    active_grid_bots: int = 0
    as_of: str

    # ── Risk guardrails (bankruptcy protection) ──────────────────────────────
    exposure_pct: float = Field(0.0, description="Capital deployed as % of total")
    max_exposure_pct: float = Field(0.0, description="Configured max total exposure %")
    cash_buffer_usd: float = Field(0.0, description="Mandatory free-cash cushion (USD)")
    max_position_usd: float = Field(0.0, description="Max notional allowed per single position")
    max_position_pct: float = Field(0.0, description="Max single position as % of capital")
    unrealized_pnl_usd: float = Field(
        0.0,
        description="Live net unrealized P&L on open maneuvers + grid (same as positions tab)",
    )
    realized_pnl_usd: float = Field(
        0.0,
        description="Sum of realized_pnl on closed maneuvers (paper ledger)",
    )
    deployed_notional_usd: float = Field(
        0.0,
        description="Capital at work (maneuver + grid notional, excluding mark-to-market)",
    )
    portfolio_allocation_usd: float = Field(
        0.0,
        description="Operator-configured capital cap the platform may deploy (settings.portfolio_size)",
    )
    account_balance_usd: float | None = Field(
        None,
        description="Live free balance across connected exchange venues (Binance etc.), when fetched",
    )
    account_total_usd: float | None = Field(
        None,
        description="Live total balance across connected exchange venues, when fetched",
    )

    @model_validator(mode="after")
    def _sanitize_non_finite_floats(self) -> Self:
        int_fields = {"open_maneuvers", "active_grid_bots"}
        for name in self.model_fields:
            val = getattr(self, name)
            if isinstance(val, Real) and not isinstance(val, bool) and not math.isfinite(float(val)):
                object.__setattr__(self, name, 0 if name in int_fields else 0.0)
        return self


class PortfolioRefreshOut(PortfolioMetricsOut):
    """Fresh portfolio metrics after reconciling stale exposure locks."""

    deactivated_grid_bots: int = 0
    released_capital_usd: float = 0.0
    reconciled_at: str = ""


class VenueBalanceOut(BaseModel):
    """Per-venue capital breakdown for the multi-venue aggregator."""

    venue: str = Field(..., description="binance | finam | tinkoff")
    configured: bool = Field(False, description="Credentials present in env")
    mode: str = Field("pending", description="testnet | demo | sandbox-stub | live | pending")
    refreshed: bool = Field(
        False,
        description="True only when a live balance was actually fetched this call "
        "(stubs / unconfigured / errored venues stay False)",
    )
    trading_usd: float = Field(0.0, description="Capital in open orders / locked (TRD)")
    balance_usd: float = Field(0.0, description="Free / available balance (BLNC)")
    total_usd: float = Field(0.0, description="trading_usd + balance_usd (SUM)")
    currency: str = "USD"
    detail: str = Field("", description="Human-readable status / valuation note")
    error: str | None = Field(None, description="Fetch error message when balance unavailable")


class VenueBalancesOut(BaseModel):
    """Aggregated per-venue balances plus grand total."""

    venues: list[VenueBalanceOut] = Field(default_factory=list)
    total_trading_usd: float = 0.0
    total_balance_usd: float = 0.0
    total_usd: float = 0.0
    currency: str = "USD"
    as_of: str


class RiskStatusOut(BaseModel):
    """Dashboard risk indicator — level, label, and plain-language explanation."""

    level: str = Field(..., description="ok | caution | block")
    label: str = Field(..., description="Short Russian label for the status dot")
    explanation: str = Field(..., description="Plain-language summary in Russian")
    contributing_factors: list[str] = Field(
        default_factory=list,
        description="Bullet points explaining why this level was chosen",
    )
    exposure_pct: float = 0.0
    max_exposure_pct: float = 0.0
    daily_max_loss_pct: float = 0.0
    open_maneuvers: int = 0
    trading_usd: float = 0.0
    cash_buffer_usd: float = 0.0
    as_of: str = ""

    @model_validator(mode="after")
    def _sanitize_non_finite_floats(self) -> Self:
        for name in self.model_fields:
            val = getattr(self, name)
            if isinstance(val, Real) and not isinstance(val, bool) and not math.isfinite(float(val)):
                default = 0 if name == "open_maneuvers" else 0.0
                object.__setattr__(self, name, default)
        return self
