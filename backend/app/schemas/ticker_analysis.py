"""Structured ticker analysis contract (market-analysis-system-spec Section 7.1)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ShapFactorContribution(BaseModel):
    feature: str
    contribution: float


class PeerComparison(BaseModel):
    sector_avg_score: float | None = None
    sector: str | None = None
    peer_count: int | None = None


class TickerAnalysisPayload(BaseModel):
    """Layer-2/4 structured object for LLM chat and forecast enrichment."""

    ticker: str
    ml_score: float | None = None
    shap_top_factors: list[ShapFactorContribution] | None = None
    factor_exposures: dict[str, float | None] = Field(default_factory=dict)
    risk_metrics: dict[str, float | None] = Field(default_factory=dict)
    scenario_results: dict[str, float | None] = Field(default_factory=dict)
    peer_comparison: PeerComparison = Field(default_factory=PeerComparison)
    factor_implied_covariance: dict[str, Any] | None = None
    data_gaps: list[str] = Field(default_factory=list)
    shap_available: bool = False
    eu_macro_snippet: str = ""
    eu_macro_indicators: dict[str, float] = Field(default_factory=dict)

    def model_dump_json_ready(self) -> dict[str, Any]:
        """Dict with explicit nulls for missing optional top-level fields."""
        data = self.model_dump(mode="json")
        if self.shap_top_factors is None:
            data["shap_top_factors"] = None
        if self.factor_implied_covariance is None:
            data["factor_implied_covariance"] = None
        return data
