"""Explainability layer domain types (Prompt 28)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class DecisionExplanation:
    """Human-readable explanation for one persisted decision."""

    decision_type: str
    summary: str
    text: str
    timestamp: datetime | None = None
    source_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InstrumentExplainabilitySnapshot:
    """Aggregated explainability read-model for one instrument."""

    instrument_id: int
    headline: str
    regime_explanation: str | None = None
    factor_explanation: str | None = None
    forecast_explanation: str | None = None
    risk_explanation: str | None = None
    recent_decisions: tuple[DecisionExplanation, ...] = ()
    source_metrics: dict[str, Any] = field(default_factory=dict)
