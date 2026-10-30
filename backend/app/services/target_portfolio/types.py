"""Inputs for target portfolio construction (Prompt 36)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

METHODS = (
    "equal_weight",
    "equal_risk_contribution",
    "hrp",
    "mean_variance",
    "black_litterman",
    "cvar",
)

MODEL_VERSION = "target_portfolio.v1"


@dataclass(frozen=True, slots=True)
class Instrument:
    ticker: str
    price: Decimal | None
    license_tag: str = "internal_only"
    display_allowed: bool = False
    lot_size: Decimal = Decimal("1")
    price_step: Decimal = Decimal("0.01")
    sector: str = ""
    issuer: str = ""
    adv: Decimal | None = None
    spread_bps: Decimal | None = None
    slippage_bps: Decimal | None = None
    mu: float | None = None
    returns: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class ConstraintSet:
    name_cap: Decimal | None = None
    sector_cap: Decimal | None = None
    issuer_cap: Decimal | None = None
    allow_shorts: bool = False
    liquidity_share: Decimal | None = None
    trade_budget: Decimal | None = None
    banned_tickers: tuple[str, ...] = ()
    banned_sectors: tuple[str, ...] = ()
    banned_issuers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ForecastView:
    """One absolute view. Built only from forecast_core fields, never filled in."""

    ticker: str
    q: float
    confidence: float


@dataclass(frozen=True, slots=True)
class TaxLot:
    lot_id: str
    ticker: str
    qty: Decimal
    cost: Decimal
    acquired: date
