"""Engine → Apex risk gate. Engines never submit venue orders."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.terminal_platform.quant.models import (
    Portfolio,
    PortfolioPositionWeights,
    QuantRiskLimits,
    ReturnSeries,
)
from app.services.terminal_platform.quant.risk_manager import pre_trade_check


# Engines may suggest size; Apex hard-caps before any book change.
_ENGINE_MAX_WEIGHT = 0.08


@dataclass
class EngineIntent:
    source: str
    symbol: str
    side: str
    confidence: float
    suggested_weight: float
    horizon: str = "5–15 days"
    rationale: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


def gate_engine_intent(
    intent: EngineIntent,
    *,
    returns: list[float] | None = None,
) -> dict[str, Any]:
    """Approve or reject a research intent. execution is always 'none' here."""
    symbol = (intent.symbol or "").strip().upper() or "UNKNOWN"
    side = (intent.side or "flat").lower()
    raw_w = abs(float(intent.suggested_weight or 0.0))
    weight = min(raw_w, _ENGINE_MAX_WEIGHT)
    if side in {"flat", "none", "hold"} or weight <= 0:
        return {
            "ok": True,
            "approved": False,
            "execution": "none",
            "paper_only": True,
            "reason": "flat_or_zero_weight",
            "capped_weight": 0.0,
            "intent": _intent_payload(intent, 0.0),
        }

    hist = returns if returns and len(returns) >= 8 else [0.004, -0.003, 0.002, -0.001] * 8
    decision = pre_trade_check(
        order_symbol=symbol,
        proposed_weight=weight,
        portfolio=Portfolio(positions=[PortfolioPositionWeights(symbol="CASH", weight=1.0)]),
        historical_returns=ReturnSeries(values=hist),
        limits=QuantRiskLimits(
            enforce=True,
            max_position_weight=_ENGINE_MAX_WEIGHT,
            max_portfolio_var=0.50,
        ),
    )
    return {
        "ok": True,
        "approved": bool(decision.approved),
        "execution": "none",
        "paper_only": True,
        "routed_via": "apex_risk_gate",
        "reason": decision.reason,
        "capped_weight": weight,
        "raw_suggested_weight": raw_w,
        "intent": _intent_payload(intent, weight),
    }


def intent_from_position(
    *,
    source: str,
    symbol: str,
    last_position: int,
    confidence: float,
    metrics: dict[str, Any] | None = None,
    suggested_weight: float = 0.05,
) -> dict[str, Any]:
    if last_position > 0:
        side = "long"
    elif last_position < 0:
        side = "short"
    else:
        side = "flat"
    return gate_engine_intent(
        EngineIntent(
            source=source,
            symbol=symbol,
            side=side,
            confidence=confidence,
            suggested_weight=suggested_weight if side != "flat" else 0.0,
            rationale=f"{source} last_position={last_position}",
            metrics=metrics or {},
        )
    )


def _intent_payload(intent: EngineIntent, capped_weight: float) -> dict[str, Any]:
    return {
        "source": intent.source,
        "symbol": intent.symbol,
        "side": intent.side,
        "confidence": float(intent.confidence),
        "suggested_weight": capped_weight,
        "horizon": intent.horizon,
        "rationale": intent.rationale,
        "metrics": intent.metrics,
    }
