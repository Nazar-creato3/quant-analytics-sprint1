"""ControlFabric domain types — risk gate, kill switch, replay."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class KillSwitchScope(str, Enum):
    SYSTEM = "system"
    PROFILE = "profile"
    SLEEVE = "sleeve"


class KillSwitchTrigger(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"


class RiskGateOutcome(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"
    BREACH_CRITICAL = "breach_critical"


@dataclass(frozen=True, slots=True)
class OpenPositionExposure:
    """Open position used for correlation and sleeve risk checks."""

    instrument_id: int
    sleeve_id: str
    market_value_usd: Decimal
    daily_pnl_usd: Decimal = Decimal("0")
    drawdown_pct: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    """Current risk metrics for profile and sleeve."""

    profile_drawdown_pct: float = 0.0
    profile_daily_loss_abs: Decimal = Decimal("0")
    sleeve_drawdown_pct: float = 0.0
    sleeve_daily_loss_abs: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class PositionSizeResult:
    base_size_usd: Decimal
    adjusted_size_usd: Decimal
    atr: float
    atr_pct: float
    scale_factor: float
    reason: str


@dataclass(frozen=True, slots=True)
class RiskGateResult:
    outcome: RiskGateOutcome
    allowed: bool
    reason: str
    position_size: PositionSizeResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def triggers_kill_switch(self) -> bool:
        return self.outcome == RiskGateOutcome.BREACH_CRITICAL


@dataclass(frozen=True, slots=True)
class KillSwitchStatus:
    active: bool
    scope: KillSwitchScope
    scope_id: str | None
    trigger_type: KillSwitchTrigger | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class ReplayIntentRecord:
    """Saved intent snapshot for historical replay."""

    intent_id: str
    instrument_id: int
    sleeve_id: str
    profile_id: str
    timestamp: str
    intent_snapshot: dict[str, Any]
    market_snapshot: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReplayDecisionRecord:
    intent_id: str
    risk_gate: dict[str, Any]
    approval_decision: dict[str, Any]
    matched: bool
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ReplayReport:
    total: int
    matched: int
    mismatched: int
    decisions: tuple[ReplayDecisionRecord, ...]


@dataclass(frozen=True, slots=True)
class PredictionReplayPoint:
    """Single historical replay observation with forward validation."""

    index: int
    timestamp: str | None
    predicted_regime: str
    predicted_regime_confidence: float
    actual_regime: str
    regime_match: bool
    forecast_confidence: float
    forecast_composite_risk_score: float
    risk_breached_count: int
    risk_breached: bool


@dataclass(frozen=True, slots=True)
class RegimeConfusionMatrix:
    """Predicted vs actual forward regime counts."""

    labels: tuple[str, ...]
    matrix: dict[str, dict[str, int]]
    accuracy: float
    total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "labels": list(self.labels),
            "matrix": self.matrix,
            "accuracy": self.accuracy,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True)
class ForecastCalibrationBin:
    confidence_min: float
    confidence_max: float
    count: int
    accuracy: float


@dataclass(frozen=True, slots=True)
class ForecastCalibrationReport:
    bins: tuple[ForecastCalibrationBin, ...]
    confidence_accuracy_correlation: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "bins": [
                {
                    "confidence_min": item.confidence_min,
                    "confidence_max": item.confidence_max,
                    "count": item.count,
                    "accuracy": item.accuracy,
                }
                for item in self.bins
            ],
            "confidence_accuracy_correlation": self.confidence_accuracy_correlation,
        }


@dataclass(frozen=True, slots=True)
class PredictionReplayReport:
    """Accuracy report for RegimeEngine/ForecastEngine/RiskEngine replay."""

    instrument_id: int
    total_points: int
    regime_accuracy: float
    confusion_matrix: RegimeConfusionMatrix
    forecast_calibration: ForecastCalibrationReport
    risk_breach_rate: float
    points: tuple[PredictionReplayPoint, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "total_points": self.total_points,
            "regime_accuracy": self.regime_accuracy,
            "confusion_matrix": self.confusion_matrix.to_dict(),
            "forecast_calibration": self.forecast_calibration.to_dict(),
            "risk_breach_rate": self.risk_breach_rate,
            "points": [
                {
                    "index": point.index,
                    "timestamp": point.timestamp,
                    "predicted_regime": point.predicted_regime,
                    "predicted_regime_confidence": point.predicted_regime_confidence,
                    "actual_regime": point.actual_regime,
                    "regime_match": point.regime_match,
                    "forecast_confidence": point.forecast_confidence,
                    "forecast_composite_risk_score": point.forecast_composite_risk_score,
                    "risk_breached_count": point.risk_breached_count,
                    "risk_breached": point.risk_breached,
                }
                for point in self.points
            ],
        }
