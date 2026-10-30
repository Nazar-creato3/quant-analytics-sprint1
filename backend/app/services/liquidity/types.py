"""Liquidity monitor domain types."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class LiquidityTarget:
    instrument_id: int
    symbol: str


@dataclass(frozen=True, slots=True)
class LiquidityAssessment:
    target: LiquidityTarget
    liquidity_score: float
    spread_bps: float | None
    depth_ratio: float
    volume_ratio: float | None
    drought: bool
    reason: str
    assessed_at: datetime
    metadata: dict[str, Any]
