"""Pydantic schemas for StressHarness API (Prompt 27)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.services.scenario.types import ScenarioName


class CustomScenarioIn(BaseModel):
    scenario: ScenarioName
    shock_strength: float = Field(gt=0.0)
    target_instrument_id: int | None = Field(default=None, gt=0)
    target_sector: str | None = None


class ScenarioImpactOut(BaseModel):
    scenario_name: ScenarioName
    shock_strength: float
    estimated_pnl_impact: float
    estimated_pnl_usd: float
    portfolio_variance_delta: float
    affected_sleeves: list[dict[str, float | str]]


class PositionReviewOut(BaseModel):
    instrument_id: int
    sleeve_id: str
    weight: float
    scenario_name: ScenarioName
    stressed_loss_fraction: float
    stressed_loss_usd: float
    sleeve_risk_budget_usd: float
    exceeds_budget: bool
    reason: str


class StressReportOut(BaseModel):
    profile_id: str
    generated_at: datetime
    portfolio_value_usd: float
    scenario_results: list[ScenarioImpactOut]
    worst_scenario: ScenarioImpactOut
    max_loss_fraction: float
    max_loss_usd: float
    positions_to_review: list[PositionReviewOut]
    metadata: dict[str, Any] = Field(default_factory=dict)
