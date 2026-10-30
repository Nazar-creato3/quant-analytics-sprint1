"""Agent context models — integrate with terminal data layer when present."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MarketContext(BaseModel):
    symbol: str | None = None
    ohlcv_summary: dict[str, Any] = Field(default_factory=dict)
    quote: dict[str, Any] = Field(default_factory=dict)
    indicators: dict[str, Any] = Field(default_factory=dict)
    regime: str | None = None
    volatility: float | None = None


class MacroContext(BaseModel):
    rates: dict[str, Any] = Field(default_factory=dict)
    inflation: dict[str, Any] = Field(default_factory=dict)
    risk_sentiment: str | None = None
    series: dict[str, Any] = Field(default_factory=dict)


class SectorContext(BaseModel):
    sector: str | None = None
    peers: list[str] = Field(default_factory=list)
    relative_strength: dict[str, Any] = Field(default_factory=dict)
    sector_metrics: dict[str, Any] = Field(default_factory=dict)


class RiskContext(BaseModel):
    limits: dict[str, Any] = Field(default_factory=dict)
    var: dict[str, Any] = Field(default_factory=dict)
    drawdown: float | None = None
    stress_scenarios: list[dict[str, Any]] = Field(default_factory=list)


class PortfolioContext(BaseModel):
    positions: list[dict[str, Any]] = Field(default_factory=list)
    allocation: dict[str, Any] = Field(default_factory=dict)
    pnl: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)


class AgentContext(BaseModel):
    """Unified structured context passed into agents.

    Sibling data-connector work can populate these fields from
    ``terminal_platform.data`` models when available.
    """

    market: MarketContext | None = None
    macro: MacroContext | None = None
    sector: SectorContext | None = None
    risk: RiskContext | None = None
    portfolio: PortfolioContext | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_llm_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)
