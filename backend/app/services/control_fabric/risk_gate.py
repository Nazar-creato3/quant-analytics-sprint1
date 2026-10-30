"""RiskGate — AntiLossGuard, RiskEngine, drawdown, daily loss, correlation, and ATR sizing."""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from app.domain.deal_intent import DealIntentRead
from app.domain.profile import ProfileRead
from app.domain.sleeve import SleeveRead
from app.services.approval.models import MarketContext
from app.services.control_fabric.anti_loss_guard import AntiLossGuard
from app.services.control_fabric.risk_engine import RiskEngine, get_risk_engine
from app.services.control_fabric.risk_types import RiskBudgetContext, RiskEngineInput
from app.services.control_fabric.types import (
    OpenPositionExposure,
    PositionSizeResult,
    RiskGateOutcome,
    RiskGateResult,
    RiskSnapshot,
)

DEFAULT_MAX_CORRELATION = 0.7
ATR_PERIOD = 14
BASE_RISK_USD = Decimal("1000")


def compute_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    period: int = ATR_PERIOD,
) -> float:
    """Average True Range from OHLC sequences."""
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
        return 0.0
    size = min(len(highs), len(lows), len(closes))
    true_ranges: list[float] = []
    for index in range(1, size):
        high = highs[index]
        low = lows[index]
        prev_close = closes[index - 1]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    if not true_ranges:
        return 0.0
    window = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
    return sum(window) / len(window)


def volatility_scaled_position_size(
    *,
    base_size_usd: Decimal,
    atr: float,
    price: float,
    profile_volatility_tolerance: float,
    target_atr_pct: float = 0.02,
) -> PositionSizeResult:
    """Reduce position size when ATR% exceeds target relative to volatility tolerance."""
    if price <= 0 or atr <= 0:
        return PositionSizeResult(
            base_size_usd=base_size_usd,
            adjusted_size_usd=base_size_usd,
            atr=atr,
            atr_pct=0.0,
            scale_factor=1.0,
            reason="no ATR data; size unchanged",
        )

    atr_pct = atr / price
    tolerance = max(profile_volatility_tolerance, 0.01)
    effective_target = target_atr_pct * (1.0 + tolerance)
    scale = min(1.0, effective_target / max(atr_pct, 1e-9))
    adjusted = (base_size_usd * Decimal(str(round(scale, 6)))).quantize(Decimal("0.01"))

    if scale < 1.0:
        reason = (
            f"ATR%={atr_pct:.4f} exceeds target {effective_target:.4f}; "
            f"size scaled by {scale:.4f}"
        )
    else:
        reason = "volatility within tolerance; size unchanged"

    return PositionSizeResult(
        base_size_usd=base_size_usd,
        adjusted_size_usd=adjusted,
        atr=atr,
        atr_pct=atr_pct,
        scale_factor=scale,
        reason=reason,
    )


class RiskGate:
    """Pre-approval risk checks for DealIntent."""

    def __init__(
        self,
        *,
        default_base_size_usd: Decimal = BASE_RISK_USD,
        anti_loss_guard: AntiLossGuard | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self.default_base_size_usd = default_base_size_usd
        self.anti_loss_guard = anti_loss_guard or AntiLossGuard()
        self.risk_engine = risk_engine or get_risk_engine()

    def check_intent(
        self,
        intent: DealIntentRead,
        profile: ProfileRead,
        sleeve: SleeveRead,
        context: MarketContext,
        *,
        snapshot: RiskSnapshot | None = None,
        open_positions: Sequence[OpenPositionExposure] = (),
        instrument_correlations: dict[int, float] | None = None,
        atr: float = 0.0,
        price: float = 0.0,
        base_size_usd: Decimal | None = None,
        risk_inputs: RiskEngineInput | None = None,
        # Optional Terminal Quant soft hook (annotate only unless enforce=True).
        terminal_quant_returns: Sequence[float] | None = None,
        terminal_quant_equity: Sequence[float] | None = None,
        terminal_quant_proposed_weight: float | None = None,
        terminal_quant_enforce: bool = False,
    ) -> RiskGateResult:
        snap = snapshot or RiskSnapshot(
            profile_drawdown_pct=context.profile_drawdown_pct,
            profile_daily_loss_abs=context.profile_daily_loss_abs,
        )
        base = base_size_usd or self.default_base_size_usd

        guard_block = self.anti_loss_guard.check(
            intent,
            profile,
            context,
            sleeve=sleeve,
            open_positions=open_positions,
            instrument_correlations=instrument_correlations,
            proposed_size_usd=base,
        )
        if guard_block is not None:
            return guard_block

        risk_assessment = None
        if risk_inputs is not None:
            risk_assessment = self.risk_engine.assess(
                risk_inputs,
                RiskBudgetContext(
                    diversification_policy=profile.diversification_policy or {},
                    max_drawdown_pct=float(profile.max_drawdown_pct),
                    sleeve_risk_budget=sleeve.risk_budget,
                    profile_max_daily_loss=profile.max_daily_loss_abs,
                ),
            )
            risk_block = self._check_risk_engine_breach(risk_assessment)
            if risk_block is not None:
                return risk_block

        diversification = profile.diversification_policy or {}
        max_correlation = float(
            diversification.get("max_correlation", DEFAULT_MAX_CORRELATION)
        )

        profile_dd_breach = self._check_drawdown(
            snap.profile_drawdown_pct,
            float(profile.max_drawdown_pct),
            label="profile",
        )
        if profile_dd_breach is not None:
            return profile_dd_breach

        profile_loss_breach = self._check_daily_loss(
            snap.profile_daily_loss_abs,
            profile.max_daily_loss_abs,
            label="profile",
        )
        if profile_loss_breach is not None:
            return profile_loss_breach

        sleeve_max_dd = self._sleeve_limit(
            diversification,
            sleeve.id,
            "max_drawdown_pct",
            float(profile.max_drawdown_pct)
            * float(sleeve.capital_allocation_pct)
            / 100.0,
        )
        sleeve_dd_breach = self._check_drawdown(
            snap.sleeve_drawdown_pct,
            sleeve_max_dd,
            label=f"sleeve {sleeve.id}",
        )
        if sleeve_dd_breach is not None:
            return sleeve_dd_breach

        sleeve_max_loss = self._sleeve_limit(
            diversification,
            sleeve.id,
            "max_daily_loss_abs",
            profile.max_daily_loss_abs * sleeve.capital_allocation_pct / Decimal("100"),
        )
        sleeve_loss_breach = self._check_daily_loss(
            snap.sleeve_daily_loss_abs,
            sleeve_max_loss,
            label=f"sleeve {sleeve.id}",
        )
        if sleeve_loss_breach is not None:
            return sleeve_loss_breach

        correlation = self._max_correlation(
            intent.instrument_id,
            open_positions,
            instrument_correlations,
            context.max_correlation_with_portfolio,
        )
        if correlation > max_correlation:
            if intent.correlation_lock:
                return RiskGateResult(
                    outcome=RiskGateOutcome.BLOCKED,
                    allowed=False,
                    reason=(
                        f"correlation {correlation:.3f} exceeds limit {max_correlation:.3f} "
                        f"with open positions"
                    ),
                    metadata={"correlation": correlation, "max_correlation": max_correlation},
                )
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason=(
                    f"correlation {correlation:.3f} exceeds diversification limit "
                    f"{max_correlation:.3f}"
                ),
                metadata={"correlation": correlation, "max_correlation": max_correlation},
            )

        position_size = volatility_scaled_position_size(
            base_size_usd=base,
            atr=atr if atr > 0 else context.instrument_volatility * price,
            price=price if price > 0 else 1.0,
            profile_volatility_tolerance=profile.volatility_tolerance,
        )

        pass_metadata: dict = {
            "correlation": correlation,
            "profile_drawdown_pct": snap.profile_drawdown_pct,
            "profile_daily_loss_abs": str(snap.profile_daily_loss_abs),
        }
        if risk_assessment is not None:
            pass_metadata["risk_assessment"] = risk_assessment.to_dict()

        if terminal_quant_returns is not None:
            from app.services.terminal_platform.quant.models import QuantRiskLimits
            from app.services.terminal_platform.quant.risk_bridge import (
                enrich_risk_gate_metadata,
            )

            proposed = (
                terminal_quant_proposed_weight
                if terminal_quant_proposed_weight is not None
                else float(position_size.scale_factor)
            )
            pass_metadata = enrich_risk_gate_metadata(
                pass_metadata,
                symbol=str(intent.instrument_id),
                proposed_weight=proposed,
                historical_returns=terminal_quant_returns,
                equity_curve=terminal_quant_equity,
                limits=QuantRiskLimits(enforce=terminal_quant_enforce),
            )
            tq = pass_metadata.get("terminal_quant") or {}
            if terminal_quant_enforce and tq.get("approved") is False:
                return RiskGateResult(
                    outcome=RiskGateOutcome.BLOCKED,
                    allowed=False,
                    reason=str(tq.get("reason") or "terminal quant pre-trade blocked"),
                    metadata=pass_metadata,
                )

        return RiskGateResult(
            outcome=RiskGateOutcome.PASSED,
            allowed=True,
            reason="risk gate passed",
            position_size=position_size,
            metadata=pass_metadata,
        )

    @staticmethod
    def _check_risk_engine_breach(assessment) -> RiskGateResult | None:
        breached = assessment.breached
        if not breached:
            return None
        breach = breached[0]
        return RiskGateResult(
            outcome=RiskGateOutcome.BLOCKED,
            allowed=False,
            reason=(
                f"RiskEngine {breach.name} exceeded: "
                f"{breach.value:.4f} > {breach.threshold:.4f} ({breach.scope})"
            ),
            metadata={
                "risk_metric": breach.name,
                "risk_value": breach.value,
                "risk_threshold": breach.threshold,
                "risk_scope": breach.scope,
                "risk_assessment": assessment.to_dict(),
            },
        )

    @staticmethod
    def _sleeve_limit(
        diversification: dict,
        sleeve_id: str,
        key: str,
        default: float | Decimal,
    ) -> float | Decimal:
        sleeve_limits = diversification.get("sleeve_limits") or {}
        sleeve_cfg = sleeve_limits.get(sleeve_id) or {}
        if key in sleeve_cfg:
            return sleeve_cfg[key]
        return default

    @staticmethod
    def _check_drawdown(
        current_pct: float,
        limit_pct: float,
        *,
        label: str,
    ) -> RiskGateResult | None:
        if current_pct >= limit_pct:
            return RiskGateResult(
                outcome=RiskGateOutcome.BREACH_CRITICAL,
                allowed=False,
                reason=f"{label} max drawdown breached: {current_pct:.2f}% >= {limit_pct:.2f}%",
                metadata={"drawdown_pct": current_pct, "limit_pct": limit_pct},
            )
        return None

    @staticmethod
    def _check_daily_loss(
        current_loss: Decimal,
        limit: Decimal,
        *,
        label: str,
    ) -> RiskGateResult | None:
        if limit <= 0:
            return None
        if current_loss >= limit:
            return RiskGateResult(
                outcome=RiskGateOutcome.BREACH_CRITICAL,
                allowed=False,
                reason=(
                    f"{label} max daily loss breached: "
                    f"{current_loss} >= {limit}"
                ),
                metadata={
                    "daily_loss_abs": str(current_loss),
                    "limit_abs": str(limit),
                },
            )
        return None

    @staticmethod
    def _max_correlation(
        instrument_id: int,
        open_positions: Sequence[OpenPositionExposure],
        instrument_correlations: dict[int, float] | None,
        context_correlation: float,
    ) -> float:
        if not open_positions:
            return context_correlation

        correlations: list[float] = [context_correlation]
        corr_map = instrument_correlations or {}
        for position in open_positions:
            if position.instrument_id == instrument_id:
                continue
            pair_key = corr_map.get(position.instrument_id)
            if pair_key is not None:
                correlations.append(pair_key)

        return max(correlations) if correlations else 0.0
