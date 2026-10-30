"""ControlFabric — risk gate, kill switch, audit journal, replay engine."""
from app.services.control_fabric.anti_loss_guard import (
    AntiLossGuard,
    CORRELATION_CLUSTER_THRESHOLD,
    cluster_exposure_usd,
    parse_market_regime,
    strategy_regime_compatible,
)
from app.services.control_fabric.audit_journal import AuditJournal, ControlFabricAuditAction
from app.services.control_fabric.fabric import ControlFabric, ControlFabricResult
from app.services.control_fabric.kill_switch import KillSwitchService
from app.services.control_fabric.replay_engine import ReplayEngine
from app.services.control_fabric.replay_validation import (
    build_regime_confusion_matrix,
    compute_forecast_calibration,
    infer_actual_regime_from_forward_prices,
    regime_classification_accuracy,
)
from app.services.control_fabric.risk_engine import RiskEngine, get_risk_engine
from app.services.control_fabric.risk_gate import RiskGate, compute_atr, volatility_scaled_position_size
from app.services.control_fabric.risk_types import (
    InstrumentRiskAssessment,
    PortfolioRiskAssessment,
    RiskBudgetContext,
    RiskEngineInput,
    RiskMetricAssessment,
)
from app.services.control_fabric.types import (
    ForecastCalibrationBin,
    ForecastCalibrationReport,
    KillSwitchScope,
    KillSwitchStatus,
    KillSwitchTrigger,
    OpenPositionExposure,
    PositionSizeResult,
    PredictionReplayPoint,
    PredictionReplayReport,
    RegimeConfusionMatrix,
    ReplayDecisionRecord,
    ReplayIntentRecord,
    ReplayReport,
    RiskGateOutcome,
    RiskGateResult,
    RiskSnapshot,
)

__all__ = [
    "AntiLossGuard",
    "CORRELATION_CLUSTER_THRESHOLD",
    "AuditJournal",
    "ControlFabric",
    "ControlFabricAuditAction",
    "ControlFabricResult",
    "ForecastCalibrationBin",
    "ForecastCalibrationReport",
    "KillSwitchScope",
    "KillSwitchService",
    "KillSwitchStatus",
    "KillSwitchTrigger",
    "OpenPositionExposure",
    "PositionSizeResult",
    "PredictionReplayPoint",
    "PredictionReplayReport",
    "RegimeConfusionMatrix",
    "ReplayDecisionRecord",
    "ReplayEngine",
    "ReplayIntentRecord",
    "ReplayReport",
    "RiskEngine",
    "RiskGate",
    "RiskGateOutcome",
    "RiskGateResult",
    "RiskSnapshot",
    "InstrumentRiskAssessment",
    "PortfolioRiskAssessment",
    "RiskBudgetContext",
    "RiskEngineInput",
    "RiskMetricAssessment",
    "build_regime_confusion_matrix",
    "cluster_exposure_usd",
    "compute_atr",
    "compute_forecast_calibration",
    "get_risk_engine",
    "infer_actual_regime_from_forward_prices",
    "parse_market_regime",
    "regime_classification_accuracy",
    "strategy_regime_compatible",
    "volatility_scaled_position_size",
]
