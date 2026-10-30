"""Shared types for the bot risk module."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class CorrelationMode(str, Enum):
    WARN = "warn"
    BLOCK = "block"


@dataclass
class BotRef:
    """Lightweight handle to an active bot runtime."""

    bot_id: str
    bot_type: str  # grid | dca | momentum
    data: dict[str, Any]


@dataclass
class PositionSizeResult:
    allowed: bool
    reason: str
    notional_usd: float = 0.0
    quantity: float = 0.0
    risk_amount_usd: float = 0.0
    risk_pct: float = 0.0
    stop_loss_price: float = 0.0


@dataclass
class CorrelationCheckResult:
    allowed: bool
    mode: CorrelationMode
    reason: str
    conflicting_bots: list[str] = field(default_factory=list)


@dataclass
class CircuitBreakerResult:
    tripped: bool
    drawdown_pct: float
    threshold_pct: float
    total_pnl: float
    allocated_usd: float
    reason: str = ""


@dataclass
class PortfolioSnapshot:
    """Aggregate view across all bot runtimes for one tick batch."""

    bots: list[BotRef]
    allocated_usd: float
    total_pnl: float
    peak_pnl: float
    drawdown_pct: float
    circuit_tripped: bool = False
    circuit_reason: str = ""


@dataclass
class NewPositionGateResult:
    allowed: bool
    reason: str
    correlation: CorrelationCheckResult | None = None
    sizing: PositionSizeResult | None = None


RiskAction = Literal["warn", "block"]
