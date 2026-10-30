"""Types for StrategyMesh — sleeve-scoped market context and regime signals."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from app.domain.enums import AssetCategory

# Avoid importing equity analytics (pandas) when only enums/dataclasses are needed.
from typing import Any


class GridMode(str, Enum):
    """GridStrategy execution scope within a sleeve (allocation stays with SleeveEngine)."""

    POINT = "point"
    DIVERSIFIED = "diversified"


class MarketRegime(str, Enum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InstrumentSnapshot:
    """Single instrument quote inside a sleeve — no global portfolio fields."""

    instrument_id: int
    symbol: str
    category: AssetCategory
    last_price: Decimal
    volatility: float = 0.0
    spread_bps: float = 0.0
    momentum: float = 0.0
    mean_reversion_z: float = 0.0
    breakout_strength: float = 0.0
    yield_pct: float = 0.0
    relative_strength: float = 0.0


@dataclass(frozen=True, slots=True)
class SleeveStrategyContext:
    """Sleeve-local scope — strategies never see profile-wide portfolio state."""

    sleeve_id: str
    category: AssetCategory
    instruments: tuple[InstrumentSnapshot, ...] = ()
    risk_budget_remaining: Decimal | None = None


@dataclass(frozen=True, slots=True)
class StrategyMarketContext:
    """Unified market context consumed by all strategies."""

    sleeve: SleeveStrategyContext
    regime: MarketRegime = MarketRegime.UNKNOWN
    session_active: bool = True
    microstructure_score: float = 0.0
    volatility_percentile: float = 0.5
    asset_class: str = "equity"
    grid_mode: GridMode = GridMode.POINT
    news_locked_instrument_ids: frozenset[int] = field(default_factory=frozenset)
    event_proximity: Any | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.microstructure_score <= 1.0:
            raise ValueError("microstructure_score must be in [0, 1]")
        if not 0.0 <= self.volatility_percentile <= 1.0:
            raise ValueError("volatility_percentile must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class RawMarketSnapshot:
    """Adapter input — venue-specific fields normalized by regime adapters."""

    instruments: tuple[InstrumentSnapshot, ...]
    session_active: bool = True
    bid_ask_imbalance: float = 0.0
    funding_rate: float | None = None
    vix_level: float | None = None
    sector_rotation_score: float = 0.0
