"""AntiLossGuard — mandatory pre-approval safety checks for RiskGate."""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from app.core.config import Settings, get_settings
from app.domain.deal_intent import DealIntentRead
from app.domain.deal_intent_enums import DealIntentDirection, RiskTag
from app.domain.enums import Strategy
from app.domain.profile import ProfileBase, ProfileMode, ProfileRead
from app.domain.sleeve import SleeveRead
from app.services.control_fabric.types import (
    OpenPositionExposure,
    RiskGateOutcome,
    RiskGateResult,
)
from app.services.profile.service import validate_live_transition
from app.services.strategy.types import GridMode, MarketRegime

CORRELATION_CLUSTER_THRESHOLD = 0.7
DEFAULT_MAX_CLUSTER_PCT = 25.0
DEFAULT_MIN_LIQUIDITY_SPREAD_BPS = 100.0
DEFAULT_MAX_FORECAST_COMPOSITE_RISK = 0.85
DEFAULT_MAX_TAIL_RISK_SCORE = 0.80


def parse_market_regime(raw: str) -> MarketRegime:
    """Normalize ``MarketContext.market_regime`` to ``MarketRegime``."""
    normalized = (raw or "unknown").strip().lower().replace("-", "_")
    aliases = {
        "trend": MarketRegime.TREND_UP,
        "trending_up": MarketRegime.TREND_UP,
        "trending_down": MarketRegime.TREND_DOWN,
        "bull": MarketRegime.TREND_UP,
        "bear": MarketRegime.TREND_DOWN,
        "sideways": MarketRegime.RANGE,
        "high_volatility": MarketRegime.HIGH_VOL,
        "low_volatility": MarketRegime.LOW_VOL,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return MarketRegime(normalized)
    except ValueError:
        return MarketRegime.UNKNOWN


def strategy_regime_compatible(
    strategy: Strategy,
    regime: MarketRegime,
    direction: DealIntentDirection,
) -> bool:
    """Mirror StrategyMesh regime gates (Prompt 6 adapters)."""
    if regime == MarketRegime.UNKNOWN:
        return True

    if strategy == Strategy.GRID:
        return regime in {MarketRegime.RANGE, MarketRegime.LOW_VOL}

    if strategy == Strategy.TREND:
        if direction == DealIntentDirection.LONG:
            return regime == MarketRegime.TREND_UP
        return regime == MarketRegime.TREND_DOWN

    if strategy == Strategy.MEAN_REVERSION:
        return regime in {MarketRegime.RANGE, MarketRegime.HIGH_VOL}

    if strategy == Strategy.HEDGE:
        return regime == MarketRegime.HIGH_VOL

    if strategy == Strategy.ROTATION:
        return regime in {MarketRegime.TREND_UP, MarketRegime.RANGE}

    return True


def is_grid_mode(intent: DealIntentRead) -> bool:
    if intent.strategy != Strategy.GRID:
        return False
    grid_mode = (intent.exit_logic or {}).get("grid_mode", GridMode.POINT.value)
    return grid_mode in {GridMode.POINT.value, GridMode.DIVERSIFIED.value}


def is_event_risk_intent(intent: DealIntentRead) -> bool:
    return intent.risk_tag == RiskTag.EVENT_RISK or bool(intent.news_lock)


def cluster_exposure_usd(
    instrument_id: int,
    open_positions: Sequence[OpenPositionExposure],
    instrument_correlations: dict[int, float] | None,
    *,
    threshold: float = CORRELATION_CLUSTER_THRESHOLD,
) -> Decimal:
    """Sum exposure for positions in the same correlated cluster (>threshold)."""
    corr_map = instrument_correlations or {}
    total = Decimal("0")
    for position in open_positions:
        if position.instrument_id == instrument_id:
            total += position.market_value_usd
            continue
        pair_corr = corr_map.get(position.instrument_id)
        if pair_corr is not None and pair_corr > threshold:
            total += position.market_value_usd
    return total


class AntiLossGuard:
    """Financial safety layer — runs before RiskGate drawdown/correlation checks."""

    def __init__(
        self,
        *,
        correlation_cluster_threshold: float = CORRELATION_CLUSTER_THRESHOLD,
        settings: Settings | None = None,
    ) -> None:
        self.correlation_cluster_threshold = correlation_cluster_threshold
        self._settings = settings

    def check(
        self,
        intent: DealIntentRead,
        profile: ProfileBase | ProfileRead,
        context,
        *,
        sleeve: SleeveRead | None = None,
        open_positions: Sequence[OpenPositionExposure] = (),
        instrument_correlations: dict[int, float] | None = None,
        proposed_size_usd: Decimal | None = None,
    ) -> RiskGateResult | None:
        """Return a blocking ``RiskGateResult`` or ``None`` when all guard checks pass."""
        settings = self._settings or get_settings()

        live_block = self._check_live_signoff(profile, settings=settings)
        if live_block is not None:
            return live_block

        news_block = self._check_news_lock(intent, context)
        if news_block is not None:
            return news_block

        drought_block = self._check_liquidity_drought(intent, context)
        if drought_block is not None:
            return drought_block

        liquidity_block = self._check_liquidity(intent, profile, context)
        if liquidity_block is not None:
            return liquidity_block

        grid_event_block = self._check_event_risk_grid_conflict(
            intent,
            open_positions,
        )
        if grid_event_block is not None:
            return grid_event_block

        regime = parse_market_regime(getattr(context, "market_regime", "unknown"))
        regime_block = self._check_regime(intent, regime)
        if regime_block is not None:
            return regime_block

        forecast_block = self._check_prediction_risk(context)
        if forecast_block is not None:
            return forecast_block

        cluster_block = self._check_cluster_risk_limit(
            intent,
            profile,
            sleeve,
            open_positions,
            instrument_correlations,
            proposed_size_usd=proposed_size_usd,
        )
        if cluster_block is not None:
            return cluster_block

        return None

    @staticmethod
    def _check_live_signoff(
        profile: ProfileBase | ProfileRead,
        *,
        settings: Settings,
    ) -> RiskGateResult | None:
        if profile.mode != ProfileMode.LIVE:
            return None
        transition = validate_live_transition(profile, settings=settings)
        if transition.allowed:
            return None
        return RiskGateResult(
            outcome=RiskGateOutcome.BLOCKED,
            allowed=False,
            reason=f"live mode blocked: paper sign-off incomplete ({'; '.join(transition.reasons)})",
            metadata={"live_transition_reasons": transition.reasons},
        )

    @staticmethod
    def _check_news_lock(intent: DealIntentRead, context) -> RiskGateResult | None:
        locked_ids = getattr(context, "news_locked_instrument_ids", frozenset())
        if intent.instrument_id in locked_ids:
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason=f"news_lock active for instrument {intent.instrument_id}",
                metadata={"news_lock": True, "instrument_id": intent.instrument_id},
            )
        if intent.news_lock:
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason="intent news_lock flag blocks entry",
                metadata={"news_lock": True},
            )
        return None

    @staticmethod
    def _check_liquidity_drought(intent: DealIntentRead, context) -> RiskGateResult | None:
        locked_ids = getattr(context, "liquidity_drought_instrument_ids", frozenset())
        if intent.instrument_id in locked_ids:
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason=f"liquidity_drought active for instrument {intent.instrument_id}",
                metadata={"liquidity_drought": True, "instrument_id": intent.instrument_id},
            )
        return None

    @staticmethod
    def _check_liquidity(
        intent: DealIntentRead,
        profile: ProfileBase | ProfileRead,
        context,
    ) -> RiskGateResult | None:
        spread_bps = float(getattr(context, "instrument_spread_bps", 0.0))
        diversification = profile.diversification_policy or {}
        max_spread = float(
            diversification.get("max_liquidity_spread_bps", DEFAULT_MIN_LIQUIDITY_SPREAD_BPS)
        )

        if spread_bps > intent.max_spread_bps:
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason=(
                    f"insufficient liquidity: spread {spread_bps:.1f} bps "
                    f"> intent max {intent.max_spread_bps} bps"
                ),
                metadata={"spread_bps": spread_bps, "max_spread_bps": intent.max_spread_bps},
            )

        if spread_bps > max_spread:
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason=(
                    f"insufficient liquidity: spread {spread_bps:.1f} bps "
                    f"> profile limit {max_spread:.1f} bps"
                ),
                metadata={"spread_bps": spread_bps, "profile_max_spread_bps": max_spread},
            )
        return None

    @staticmethod
    def _check_prediction_risk(context) -> RiskGateResult | None:
        """Block when ForecastEngine/RiskEngine stack signals extreme tail risk."""
        breach_count = int(getattr(context, "risk_engine_breach_count", 0))
        if breach_count > 0:
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason=(
                    f"RiskEngine reported {breach_count} breached metric(s) "
                    "before DealIntent approval"
                ),
                metadata={
                    "risk_engine_breach_count": breach_count,
                    "forecast_composite_risk_score": getattr(
                        context,
                        "forecast_composite_risk_score",
                        0.0,
                    ),
                },
            )

        composite_risk = float(getattr(context, "forecast_composite_risk_score", 0.0))
        if composite_risk >= DEFAULT_MAX_FORECAST_COMPOSITE_RISK:
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason=(
                    f"forecast composite risk {composite_risk:.3f} exceeds "
                    f"limit {DEFAULT_MAX_FORECAST_COMPOSITE_RISK:.3f}"
                ),
                metadata={"forecast_composite_risk_score": composite_risk},
            )

        tail_risk = float(getattr(context, "tail_risk_score", 0.0))
        if tail_risk >= DEFAULT_MAX_TAIL_RISK_SCORE:
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason=(
                    f"tail risk score {tail_risk:.3f} exceeds "
                    f"limit {DEFAULT_MAX_TAIL_RISK_SCORE:.3f}"
                ),
                metadata={"tail_risk_score": tail_risk},
            )
        return None

    @staticmethod
    def _check_regime(
        intent: DealIntentRead,
        regime: MarketRegime,
    ) -> RiskGateResult | None:
        if strategy_regime_compatible(intent.strategy, regime, intent.direction):
            return None
        return RiskGateResult(
            outcome=RiskGateOutcome.BLOCKED,
            allowed=False,
            reason=(
                f"strategy {intent.strategy.value} incompatible with "
                f"market regime {regime.value} for {intent.direction.value} entry"
            ),
            metadata={
                "strategy": intent.strategy.value,
                "regime": regime.value,
                "direction": intent.direction.value,
            },
        )

    @staticmethod
    def _check_event_risk_grid_conflict(
        intent: DealIntentRead,
        open_positions: Sequence[OpenPositionExposure],
    ) -> RiskGateResult | None:
        if is_grid_mode(intent) and is_event_risk_intent(intent):
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason=(
                    f"event-risk and grid mode forbidden on same instrument "
                    f"{intent.instrument_id}"
                ),
                metadata={"instrument_id": intent.instrument_id},
            )

        for position in open_positions:
            if position.instrument_id != intent.instrument_id:
                continue
            position_is_grid = position.metadata.get("strategy") == Strategy.GRID.value
            position_is_event = position.metadata.get("risk_tag") == RiskTag.EVENT_RISK.value
            if is_grid_mode(intent) and position_is_event:
                return RiskGateResult(
                    outcome=RiskGateOutcome.BLOCKED,
                    allowed=False,
                    reason=(
                        f"grid entry forbidden: open event-risk exposure on "
                        f"instrument {intent.instrument_id}"
                    ),
                    metadata={"instrument_id": intent.instrument_id},
                )
            if is_event_risk_intent(intent) and position_is_grid:
                return RiskGateResult(
                    outcome=RiskGateOutcome.BLOCKED,
                    allowed=False,
                    reason=(
                        f"event-risk entry forbidden: open grid exposure on "
                        f"instrument {intent.instrument_id}"
                    ),
                    metadata={"instrument_id": intent.instrument_id},
                )
        return None

    def _check_cluster_risk_limit(
        self,
        intent: DealIntentRead,
        profile: ProfileBase | ProfileRead,
        sleeve: SleeveRead | None,
        open_positions: Sequence[OpenPositionExposure],
        instrument_correlations: dict[int, float] | None,
        *,
        proposed_size_usd: Decimal | None,
    ) -> RiskGateResult | None:
        diversification = profile.diversification_policy or {}
        max_cluster_pct = float(
            diversification.get("max_correlation_cluster_pct", DEFAULT_MAX_CLUSTER_PCT)
        )
        if max_cluster_pct <= 0:
            return None

        cluster_usd = cluster_exposure_usd(
            intent.instrument_id,
            open_positions,
            instrument_correlations,
            threshold=self.correlation_cluster_threshold,
        )
        if cluster_usd <= 0:
            return None

        proposed = proposed_size_usd or Decimal("0")
        total_cluster = cluster_usd + proposed

        budget = Decimal("0")
        if sleeve is not None and sleeve.risk_budget > 0:
            budget = sleeve.risk_budget
        elif profile.max_daily_loss_abs > 0:
            budget = profile.max_daily_loss_abs
        else:
            budget = Decimal("100000")

        limit_usd = (budget * Decimal(str(max_cluster_pct)) / Decimal("100")).quantize(
            Decimal("0.01")
        )

        if total_cluster > limit_usd:
            return RiskGateResult(
                outcome=RiskGateOutcome.BLOCKED,
                allowed=False,
                reason=(
                    f"correlated cluster exposure {total_cluster} exceeds "
                    f"limit {limit_usd} ({max_cluster_pct}% of budget)"
                ),
                metadata={
                    "cluster_exposure_usd": str(total_cluster),
                    "cluster_limit_usd": str(limit_usd),
                    "correlation_threshold": self.correlation_cluster_threshold,
                },
            )
        return None
