"""Concrete strategy implementations for StrategyMesh."""
from __future__ import annotations

from decimal import Decimal

from app.domain.deal_intent import DealIntentCreate
from app.domain.deal_intent_enums import DealIntentDirection, RiskTag, TriggerType
from app.domain.enums import AssetCategory, Strategy

from app.services.strategy.base import BaseStrategy
from app.services.strategy.types import GridMode, InstrumentSnapshot, MarketRegime, StrategyMarketContext


class GridStrategy(BaseStrategy):
    """Range-bound grid — point (1 instrument) or diversified (N instruments in sleeve)."""

    strategy = Strategy.GRID
    allowed_sleeve_categories = frozenset(
        {AssetCategory.CRYPTO, AssetCategory.SPECULATIVE_SLEEVE, AssetCategory.FX}
    )

    def _analyze_sleeve(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        if market_context.grid_mode == GridMode.DIVERSIFIED:
            intents = self.analyze_diversified(market_context)
            return intents[0] if intents else None
        return self._analyze_point(market_context)

    def _analyze_point(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        instruments = self._eligible_instruments(market_context)
        if len(instruments) != 1:
            return None
        return self._grid_intent(market_context, instruments[0])

    def analyze_diversified(
        self,
        market_context: StrategyMarketContext,
    ) -> tuple[DealIntentCreate, ...]:
        """Produce one draft intent per eligible sleeve instrument (no allocation logic)."""
        if not self._sleeve_allowed(market_context):
            return ()
        instruments = self._eligible_instruments(market_context)
        if len(instruments) < 2:
            return ()
        if market_context.regime not in {MarketRegime.RANGE, MarketRegime.LOW_VOL, MarketRegime.UNKNOWN}:
            return ()

        intents: list[DealIntentCreate] = []
        for instrument in instruments:
            intent = self._grid_intent(market_context, instrument)
            if intent is not None:
                intents.append(intent)
        return tuple(intents)

    def _grid_intent(
        self,
        market_context: StrategyMarketContext,
        instrument: InstrumentSnapshot,
    ) -> DealIntentCreate | None:
        if market_context.regime not in {MarketRegime.RANGE, MarketRegime.LOW_VOL, MarketRegime.UNKNOWN}:
            return None
        if instrument.volatility > 0.45:
            return None

        grid_step = instrument.last_price * Decimal("0.01")
        return self._draft_intent(
            market_context=market_context,
            instrument=instrument,
            direction=DealIntentDirection.LONG,
            entry_reason=f"grid {market_context.grid_mode.value} entry below mid in {instrument.symbol}",
            required_confidence=0.65,
            risk_tag=RiskTag.MEDIUM,
            trigger_type=TriggerType.LIMIT,
            target_price=instrument.last_price - grid_step,
            exit_logic={"take_profit_pct": 1.0, "stop_loss_pct": 3.0, "grid_mode": market_context.grid_mode.value},
        )


class TrendStrategy(BaseStrategy):
    strategy = Strategy.TREND
    allowed_sleeve_categories = frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.ETF,
            AssetCategory.CRYPTO,
            AssetCategory.INDICES,
            AssetCategory.SPECULATIVE_SLEEVE,
        }
    )

    def _analyze_sleeve(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        instruments = self._eligible_instruments(market_context)
        if not instruments:
            return None

        if market_context.regime == MarketRegime.TREND_UP:
            leader = max(instruments, key=lambda item: item.momentum)
            if leader.momentum < 0.1:
                return None
            return self._draft_intent(
                market_context=market_context,
                instrument=leader,
                direction=DealIntentDirection.LONG,
                entry_reason=f"trend follow long on {leader.symbol}",
                required_confidence=min(0.95, 0.6 + leader.momentum),
                risk_tag=RiskTag.MEDIUM,
                trigger_type=TriggerType.MARKET,
                exit_logic={"trailing_stop_pct": 5.0},
            )

        if market_context.regime == MarketRegime.TREND_DOWN:
            leader = min(instruments, key=lambda item: item.momentum)
            if leader.momentum > -0.1:
                return None
            return self._draft_intent(
                market_context=market_context,
                instrument=leader,
                direction=DealIntentDirection.SHORT,
                entry_reason=f"trend follow short on {leader.symbol}",
                required_confidence=min(0.95, 0.6 + abs(leader.momentum)),
                risk_tag=RiskTag.HIGH,
                trigger_type=TriggerType.MARKET,
                exit_logic={"trailing_stop_pct": 5.0},
            )
        return None


class MeanReversionStrategy(BaseStrategy):
    strategy = Strategy.MEAN_REVERSION
    allowed_sleeve_categories = frozenset(
        {AssetCategory.EQUITIES, AssetCategory.ETF, AssetCategory.FX, AssetCategory.CRYPTO}
    )

    def _analyze_sleeve(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        if market_context.regime not in {MarketRegime.RANGE, MarketRegime.HIGH_VOL, MarketRegime.UNKNOWN}:
            return None

        instruments = self._eligible_instruments(market_context)
        if not instruments:
            return None

        candidate = max(instruments, key=lambda item: abs(item.mean_reversion_z))
        if abs(candidate.mean_reversion_z) < 1.5:
            return None

        direction = (
            DealIntentDirection.LONG
            if candidate.mean_reversion_z < 0
            else DealIntentDirection.SHORT
        )
        return self._draft_intent(
            market_context=market_context,
            instrument=candidate,
            direction=direction,
            entry_reason=f"mean reversion z={candidate.mean_reversion_z:.2f} on {candidate.symbol}",
            required_confidence=min(0.9, 0.5 + abs(candidate.mean_reversion_z) * 0.15),
            risk_tag=RiskTag.MEDIUM,
            trigger_type=TriggerType.LIMIT,
            exit_logic={"take_profit_z": 0.0, "stop_loss_z": 3.0},
        )


class BreakoutStrategy(BaseStrategy):
    strategy = Strategy.BREAKOUT
    allowed_sleeve_categories = frozenset(
        {
            AssetCategory.EQUITIES,
            AssetCategory.CRYPTO,
            AssetCategory.SPECULATIVE_SLEEVE,
            AssetCategory.COMMODITIES,
        }
    )

    def _analyze_sleeve(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        instruments = self._eligible_instruments(market_context)
        if not instruments:
            return None

        candidate = max(instruments, key=lambda item: item.breakout_strength)
        if candidate.breakout_strength < 0.6:
            return None

        return self._draft_intent(
            market_context=market_context,
            instrument=candidate,
            direction=DealIntentDirection.LONG,
            entry_reason=f"breakout strength={candidate.breakout_strength:.2f} on {candidate.symbol}",
            required_confidence=min(0.92, 0.55 + candidate.breakout_strength * 0.4),
            risk_tag=RiskTag.HIGH,
            trigger_type=TriggerType.STOP,
            exit_logic={"stop_loss_pct": 2.5, "take_profit_pct": 8.0},
        )


class HedgeStrategy(BaseStrategy):
    strategy = Strategy.HEDGE
    allowed_sleeve_categories = frozenset(
        {AssetCategory.MACRO_HEDGE, AssetCategory.DEFENSIVE_SLEEVE, AssetCategory.RATES_BONDS}
    )

    def _analyze_sleeve(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        if market_context.regime != MarketRegime.HIGH_VOL:
            return None

        instruments = self._eligible_instruments(market_context)
        if not instruments:
            return None

        hedge = min(instruments, key=lambda item: item.momentum)
        return self._draft_intent(
            market_context=market_context,
            instrument=hedge,
            direction=DealIntentDirection.LONG,
            entry_reason=f"defensive hedge in high-vol regime via {hedge.symbol}",
            required_confidence=0.75,
            risk_tag=RiskTag.LOW,
            trigger_type=TriggerType.MARKET,
            exit_logic={"time_exit_days": 30},
        )


class IncomeStrategy(BaseStrategy):
    strategy = Strategy.INCOME
    allowed_sleeve_categories = frozenset(
        {AssetCategory.INCOME_SLEEVE, AssetCategory.RATES_BONDS, AssetCategory.ETF}
    )

    def _analyze_sleeve(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        instruments = self._eligible_instruments(market_context)
        if not instruments:
            return None

        candidate = max(instruments, key=lambda item: item.yield_pct)
        if candidate.yield_pct < 2.0:
            return None

        return self._draft_intent(
            market_context=market_context,
            instrument=candidate,
            direction=DealIntentDirection.LONG,
            entry_reason=f"income sleeve yield={candidate.yield_pct:.2f}% on {candidate.symbol}",
            required_confidence=0.7,
            risk_tag=RiskTag.LOW,
            trigger_type=TriggerType.LIMIT,
            exit_logic={"min_hold_days": 90, "yield_target_pct": candidate.yield_pct},
        )


class RotationStrategy(BaseStrategy):
    strategy = Strategy.ROTATION
    allowed_sleeve_categories = frozenset(
        {AssetCategory.THEMATIC_BASKET, AssetCategory.SECTOR_BASKET, AssetCategory.ETF}
    )

    def _analyze_sleeve(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        if market_context.regime not in {MarketRegime.TREND_UP, MarketRegime.RANGE}:
            return None

        instruments = self._eligible_instruments(market_context)
        if len(instruments) < 2:
            return None

        leader = max(instruments, key=lambda item: item.relative_strength)
        if leader.relative_strength < 0.05:
            return None

        return self._draft_intent(
            market_context=market_context,
            instrument=leader,
            direction=DealIntentDirection.LONG,
            entry_reason=f"sector rotation leader rs={leader.relative_strength:.2f} on {leader.symbol}",
            required_confidence=min(0.88, 0.6 + leader.relative_strength),
            risk_tag=RiskTag.MEDIUM,
            trigger_type=TriggerType.MARKET,
            exit_logic={"rotate_on_rs_drop": 0.02},
        )


class VolatilityHarvestingStrategy(BaseStrategy):
    strategy = Strategy.VOLATILITY_HARVESTING
    allowed_sleeve_categories = frozenset(
        {AssetCategory.CRYPTO, AssetCategory.FX, AssetCategory.COMMODITIES}
    )

    def _analyze_sleeve(self, market_context: StrategyMarketContext) -> DealIntentCreate | None:
        if market_context.volatility_percentile < 0.55:
            return None

        instruments = self._eligible_instruments(market_context)
        if not instruments:
            return None

        candidate = max(instruments, key=lambda item: item.volatility)
        if candidate.volatility < 0.2:
            return None

        return self._draft_intent(
            market_context=market_context,
            instrument=candidate,
            direction=DealIntentDirection.LONG,
            entry_reason=(
                f"vol harvest iv_pct={market_context.volatility_percentile:.2f} "
                f"on {candidate.symbol}"
            ),
            required_confidence=min(0.85, 0.5 + market_context.volatility_percentile * 0.4),
            risk_tag=RiskTag.HIGH,
            trigger_type=TriggerType.CONDITION,
            exit_logic={"vol_target_percentile": 0.4, "premium_capture_pct": 3.0},
        )
