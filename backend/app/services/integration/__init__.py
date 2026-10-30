"""End-to-end validation pipeline — Profile → Sleeve → DealIntent → paper execution."""

from app.services.integration.report import CombinedValidationReport, ValidationReport
from app.services.integration.types import HistoricalBar, IntentGateOutcome

__all__ = [
    "CombinedValidationReport",
    "FullStackValidationReport",
    "HistoricalBar",
    "IntentGateOutcome",
    "PredictionRiskStack",
    "PredictionRiskStackContext",
    "RiskGateValidationMetrics",
    "ValidationReport",
    "run_full_stack_validation",
]


def __getattr__(name: str):
    if name == "ValidationPipeline":
        from app.services.integration.pipeline import ValidationPipeline

        return ValidationPipeline
    if name == "PredictionRiskStack":
        from app.services.integration.stack import PredictionRiskStack

        return PredictionRiskStack
    if name == "PredictionRiskStackContext":
        from app.services.integration.stack import PredictionRiskStackContext

        return PredictionRiskStackContext
    if name in {
        "FullStackValidationReport",
        "RiskGateValidationMetrics",
        "run_full_stack_validation",
    }:
        from app.services.integration import full_stack_validation as module

        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
