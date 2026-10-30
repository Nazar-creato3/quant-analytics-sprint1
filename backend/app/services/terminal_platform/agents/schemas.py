"""Structured agent response schemas."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    MARKET_ANALYST = "market_analyst"
    MACRO_ANALYST = "macro_analyst"
    SECTOR_ANALYST = "sector_analyst"
    PORTFOLIO_STRATEGIST = "portfolio_strategist"
    RISK_OFFICER = "risk_officer"
    TRADE_EXECUTOR = "trade_executor"
    ORCHESTRATOR = "orchestrator"


class AgentAnswer(BaseModel):
    """Canonical structured output for every terminal agent."""

    answer: str = Field(..., description="Human-readable analysis / recommendation")
    confidence: float = Field(..., ge=0.0, le=1.0, description="0–1 confidence score")
    confidence_reason: str = Field(..., description="Why this confidence level")
    data_sources: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    agent_type: AgentType | str | None = None
    provider: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    steps: list[str] = Field(default_factory=list)
    tools_needed: list[str] = Field(default_factory=list)
    focus_symbols: list[str] = Field(default_factory=list)


class AgentResult(BaseModel):
    plan: AgentPlan
    answer: AgentAnswer
    raw_llm: str | None = None


class OrchestratorSubResult(BaseModel):
    agent_type: AgentType | str
    answer: AgentAnswer


class OrchestratorResult(BaseModel):
    """Aggregated multi-agent response (ASKB-like)."""

    query: str
    decomposition: list[str] = Field(default_factory=list)
    sub_results: list[OrchestratorSubResult] = Field(default_factory=list)
    aggregated: AgentAnswer
