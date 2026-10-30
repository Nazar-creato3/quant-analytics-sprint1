"""Multi-level approval policy evaluation for DealIntent."""
from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.domain.deal_intent import DealIntentRead
from app.domain.deal_intent_enums import RiskTag
from app.domain.enums import AssetCategory, SleeveStatus
from app.domain.profile import ProfileBase, ProfileMode, RiskAppetite
from app.services.approval.models import MarketContext, PolicyDecision, PolicyState
from app.services.compliance import resolve_effective_profile_access


class DealIntentForPolicy(Protocol):
    """Minimal DealIntent surface consumed by ApprovalPolicyEngine."""

    id: str
    instrument_id: int
    sleeve_id: str
    required_confidence: float
    max_spread_bps: int
    approval_threshold: Decimal
    risk_tag: RiskTag
    news_lock: bool
    correlation_lock: bool
    volatility_lock: bool


RISK_TAG_BASE: dict[RiskTag, float] = {
    RiskTag.LOW: 0.15,
    RiskTag.MEDIUM: 0.45,
    RiskTag.HIGH: 0.72,
    RiskTag.EVENT_RISK: 0.88,
}

AUTO_APPROVE_MAX_RISK = 0.35
CONDITIONAL_MAX_RISK = 0.65


def compute_risk_score(
    intent: DealIntentForPolicy,
    context: MarketContext | None = None,
) -> float:
    """Aggregate intent risk signals into a normalized [0, 1] score."""
    score = RISK_TAG_BASE[intent.risk_tag]
    score += (1.0 - intent.required_confidence) * 0.25
    if intent.news_lock:
        score += 0.12
    if intent.correlation_lock:
        score += 0.08
    if intent.volatility_lock:
        score += 0.08
    if context is not None:
        score += context.forecast_composite_risk_score * 0.20
        score += context.tail_risk_score * 0.10
        if context.risk_engine_breach_count > 0:
            score += min(0.25, 0.08 * context.risk_engine_breach_count)
        if context.risk_flags:
            score += min(0.15, 0.03 * len(context.risk_flags))
    return min(1.0, max(0.0, score))


def _correlation_threshold(profile: ProfileBase) -> float:
    policy = profile.diversification_policy or {}
    raw = policy.get("max_correlation", policy.get("max_correlation_cluster", 0.7))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.7
    return min(1.0, max(0.0, value))


def _category_allowed(
    profile: ProfileBase,
    context: MarketContext,
) -> bool:
    effective = resolve_effective_profile_access(profile)
    category = context.instrument_category
    if category is None:
        return True
    if not effective.allowed_categories:
        return False
    return category in effective.allowed_categories


def _instrument_allowed(profile: ProfileBase, intent: DealIntentForPolicy) -> bool:
    effective = resolve_effective_profile_access(profile)
    allowed = effective.allowed_instruments
    if not allowed:
        return True
    return intent.instrument_id in allowed


def _profile_drawdown_breached(profile: ProfileBase, context: MarketContext) -> bool:
    limit = float(profile.max_drawdown_pct)
    return context.profile_drawdown_pct >= limit


def _profile_daily_loss_breached(profile: ProfileBase, context: MarketContext) -> bool:
    limit = profile.max_daily_loss_abs
    if limit <= 0:
        return False
    return context.profile_daily_loss_abs >= limit


def _sleeve_budget_exhausted(context: MarketContext) -> bool:
    remaining = context.sleeve_risk_budget_remaining
    return remaining is not None and remaining <= Decimal("0")


def _conditional_conditions_met(
    intent: DealIntentForPolicy,
    profile: ProfileBase,
    context: MarketContext,
) -> tuple[bool, list[str]]:
    failures: list[str] = []

    if context.instrument_volatility > profile.volatility_tolerance:
        failures.append(
            f"instrument volatility {context.instrument_volatility:.3f} exceeds "
            f"profile tolerance {profile.volatility_tolerance:.3f}"
        )

    if context.instrument_spread_bps > intent.max_spread_bps:
        failures.append(
            f"spread {context.instrument_spread_bps:.1f} bps exceeds "
            f"intent max {intent.max_spread_bps} bps"
        )

    if intent.instrument_id in context.news_locked_instrument_ids or intent.news_lock:
        failures.append("active news lock blocks conditional approval")

    if intent.instrument_id in context.liquidity_drought_instrument_ids:
        failures.append("liquidity_drought lock blocks conditional approval")

    if intent.instrument_id in context.active_lock_instrument_ids:
        failures.append("active_locks table blocks conditional approval for instrument")

    if intent.sleeve_id in context.active_lock_sleeve_ids:
        failures.append("active_locks table blocks conditional approval for sleeve")

    corr_threshold = _correlation_threshold(profile)
    if context.max_correlation_with_portfolio > corr_threshold:
        failures.append(
            f"portfolio correlation {context.max_correlation_with_portfolio:.3f} "
            f"exceeds threshold {corr_threshold:.3f}"
        )

    if intent.volatility_lock and context.instrument_volatility > profile.volatility_tolerance * 0.8:
        failures.append("volatility_lock active while realized volatility is elevated")

    preferred_regimes = (profile.session_preferences or {}).get("preferred_regimes", [])
    if preferred_regimes and context.market_regime not in preferred_regimes:
        failures.append(
            f"market regime '{context.market_regime}' not in preferred {preferred_regimes}"
        )

    return len(failures) == 0, failures


def _requires_manual_review(
    intent: DealIntentForPolicy,
    profile: ProfileBase,
    risk_score: float,
) -> bool:
    if risk_score >= float(intent.approval_threshold):
        return True
    if intent.risk_tag == RiskTag.EVENT_RISK:
        return True
    if profile.news_sensitivity >= 0.8 and intent.news_lock:
        return True
    if profile.event_sensitivity >= 0.8 and intent.risk_tag in {RiskTag.HIGH, RiskTag.EVENT_RISK}:
        return True
    return False


def _intent_changes_position_size(intent: DealIntentRead | DealIntentForPolicy) -> bool:
    """True when intent exit_logic declares an explicit position size change."""
    exit_logic = getattr(intent, "exit_logic", None) or {}
    if exit_logic.get("position_size_usd") or exit_logic.get("delta_weight"):
        return True
    return False


def evaluate_policy(
    intent: DealIntentRead | DealIntentForPolicy,
    profile: ProfileBase,
    context: MarketContext,
) -> PolicyDecision:
    """Evaluate DealIntent against profile constitution and market context."""
    risk_score = compute_risk_score(intent, context)
    meta: dict[str, object] = {
        "risk_score": risk_score,
        "deal_intent_id": intent.id,
        "dominant_regime": context.dominant_regime,
        "forecast_confidence": context.forecast_confidence,
        "forecast_composite_risk_score": context.forecast_composite_risk_score,
        "risk_engine_breach_count": context.risk_engine_breach_count,
        "proposed_delta_var": context.proposed_delta_var,
        "marginal_risk_computed": context.marginal_risk_computed,
    }

    if _intent_changes_position_size(intent) and not context.marginal_risk_computed:
        return PolicyDecision(
            state=PolicyState.HOLD_FOR_REVIEW,
            reason=(
                "Marginal risk what_if not computed for sizing-changing intent — "
                "proposed_delta_var is mandatory before approval"
            ),
            risk_score=risk_score,
            metadata=meta,
        )

    if context.session_killed:
        return PolicyDecision(
            state=PolicyState.KILL_SESSION,
            reason=(
                "Profile session is killed; all pending and executing intents are stopped "
                "until manual unlock"
            ),
            risk_score=risk_score,
            metadata=meta,
        )

    if _profile_drawdown_breached(profile, context) or _profile_daily_loss_breached(profile, context):
        return PolicyDecision(
            state=PolicyState.KILL_SESSION,
            reason=(
                "Critical profile risk breach (drawdown or daily loss limit); "
                "session kill switch engaged"
            ),
            risk_score=risk_score,
            metadata={
                **meta,
                "drawdown_pct": context.profile_drawdown_pct,
                "daily_loss_abs": str(context.profile_daily_loss_abs),
            },
        )

    if (
        context.sleeve_status == SleeveStatus.FROZEN
        or context.freeze_sleeve_requested
        or _sleeve_budget_exhausted(context)
    ):
        reason_parts = []
        if context.sleeve_status == SleeveStatus.FROZEN:
            reason_parts.append("sleeve is frozen")
        if context.freeze_sleeve_requested:
            reason_parts.append("sleeve freeze requested by risk controls")
        if _sleeve_budget_exhausted(context):
            reason_parts.append("sleeve risk budget exhausted")
        return PolicyDecision(
            state=PolicyState.FREEZE_SLEEVE,
            reason=f"Sleeve frozen: {'; '.join(reason_parts)}; pending intents move to held",
            risk_score=risk_score,
            metadata={**meta, "sleeve_id": intent.sleeve_id},
        )

    hard_reject_reasons: list[str] = []
    if not _category_allowed(profile, context):
        hard_reject_reasons.append(
            f"instrument category {context.instrument_category} not in profile allowed_categories"
        )
    if not _instrument_allowed(profile, intent):
        hard_reject_reasons.append(
            f"instrument_id {intent.instrument_id} not in profile allowed_instrument_ids override list"
        )
    if profile.mode == ProfileMode.LIVE and profile.risk_appetite == RiskAppetite.CONSERVATIVE:
        if intent.risk_tag in {RiskTag.HIGH, RiskTag.EVENT_RISK}:
            hard_reject_reasons.append(
                "conservative live profile cannot accept high or event_risk intents"
            )

    corr_threshold = _correlation_threshold(profile)
    if intent.correlation_lock and context.max_correlation_with_portfolio > corr_threshold:
        hard_reject_reasons.append(
            f"correlation_lock violated: exposure {context.max_correlation_with_portfolio:.3f} "
            f"> threshold {corr_threshold:.3f}"
        )

    if hard_reject_reasons:
        return PolicyDecision(
            state=PolicyState.REJECT_HARD,
            reason="; ".join(hard_reject_reasons),
            risk_score=risk_score,
            metadata=meta,
        )

    if _requires_manual_review(intent, profile, risk_score):
        return PolicyDecision(
            state=PolicyState.HOLD_FOR_REVIEW,
            reason=(
                f"Risk score {risk_score:.3f} requires manual review "
                f"(threshold {float(intent.approval_threshold):.3f}, tag {intent.risk_tag.value})"
            ),
            risk_score=risk_score,
            metadata=meta,
        )

    if risk_score <= AUTO_APPROVE_MAX_RISK and _category_allowed(profile, context):
        if (
            context.remaining_risk_budget_var is not None
            and context.proposed_delta_var > context.remaining_risk_budget_var
        ):
            return PolicyDecision(
                state=PolicyState.HOLD_FOR_REVIEW,
                reason=(
                    f"Marginal delta_var {context.proposed_delta_var:.4f} exceeds remaining "
                    f"risk budget {context.remaining_risk_budget_var:.4f} — cannot auto_approve"
                ),
                risk_score=risk_score,
                metadata=meta,
            )
        conditions_ok, _ = _conditional_conditions_met(intent, profile, context)
        if conditions_ok:
            return PolicyDecision(
                state=PolicyState.AUTO_APPROVE,
                reason=(
                    f"Low risk score {risk_score:.3f} with full profile compliance "
                    "and favorable market context"
                ),
                risk_score=risk_score,
                conditions_met=True,
                metadata=meta,
            )

    conditions_ok, failures = _conditional_conditions_met(intent, profile, context)
    if conditions_ok and risk_score <= CONDITIONAL_MAX_RISK:
        return PolicyDecision(
            state=PolicyState.CONDITIONAL_APPROVE,
            reason=(
                f"Medium risk score {risk_score:.3f}; conditional market checks passed "
                f"(volatility, spread, news, correlation, regime)"
            ),
            risk_score=risk_score,
            conditions_met=True,
            metadata=meta,
        )

    hold_reason = (
        f"Conditional approval checks failed: {'; '.join(failures)}"
        if failures
        else f"Risk score {risk_score:.3f} exceeds auto-approve band without manual review flag"
    )
    return PolicyDecision(
        state=PolicyState.HOLD_FOR_REVIEW,
        reason=hold_reason,
        risk_score=risk_score,
        conditions_met=False,
        metadata={**meta, "failures": failures},
    )
