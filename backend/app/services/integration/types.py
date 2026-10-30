"""Shared types for integration validation pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.domain.enums import AssetCategory, Strategy


@dataclass(frozen=True, slots=True)
class HistoricalBar:
    """Normalized OHLCV bar from any venue."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    symbol: str


@dataclass(frozen=True, slots=True)
class IntentGateOutcome:
    """Explainability record for a rejected or held intent."""

    intent_id: str
    strategy: Strategy
    instrument_id: int
    symbol: str
    stage: str
    status: str
    reason: str
    explainability: dict[str, Any] = field(default_factory=dict)
    bar_timestamp: str = ""


@dataclass(frozen=True, slots=True)
class PaperTrade:
    """Simulated round-trip for validation metrics."""

    intent_id: str
    strategy: Strategy
    symbol: str
    entry_price: float
    exit_price: float
    return_pct: float
    entry_ts: str
    exit_ts: str


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """In-memory audit journal row mirroring ControlFabric actions."""

    action: str
    resource_id: str | None
    success: bool
    details: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class VenueConfig:
    """Instrument metadata for a replay venue."""

    source: str
    symbol: str
    instrument_id: int
    category: AssetCategory
    sleeve_id: str = "sleeve-1"
