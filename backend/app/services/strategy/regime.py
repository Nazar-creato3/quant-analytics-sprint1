"""Market regime adapters — crypto (24/7 microstructure) vs equity (session-based)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.enums import AssetCategory

from app.services.strategy.types import (
    MarketRegime,
    RawMarketSnapshot,
    SleeveStrategyContext,
    StrategyMarketContext,
)


def _infer_regime(snapshot: RawMarketSnapshot) -> MarketRegime:
    if not snapshot.instruments:
        return MarketRegime.UNKNOWN

    avg_momentum = sum(item.momentum for item in snapshot.instruments) / len(snapshot.instruments)
    avg_vol = sum(item.volatility for item in snapshot.instruments) / len(snapshot.instruments)

    if avg_vol >= 0.35:
        return MarketRegime.HIGH_VOL
    if avg_vol <= 0.08:
        return MarketRegime.LOW_VOL
    if avg_momentum >= 0.15:
        return MarketRegime.TREND_UP
    if avg_momentum <= -0.15:
        return MarketRegime.TREND_DOWN
    return MarketRegime.RANGE


class RegimeAdapter(ABC):
    """Build a unified ``StrategyMarketContext`` from venue-specific snapshots."""

    asset_class: str

    @abstractmethod
    def build_context(
        self,
        raw: RawMarketSnapshot,
        sleeve: SleeveStrategyContext,
        *,
        news_locked_instrument_ids: frozenset[int] | None = None,
    ) -> StrategyMarketContext:
        raise NotImplementedError


class CryptoRegimeAdapter(RegimeAdapter):
    """24/7 crypto markets — microstructure-heavy regime detection."""

    asset_class = "crypto"

    def build_context(
        self,
        raw: RawMarketSnapshot,
        sleeve: SleeveStrategyContext,
        *,
        news_locked_instrument_ids: frozenset[int] | None = None,
    ) -> StrategyMarketContext:
        sleeve_instruments = tuple(
            item for item in raw.instruments if item.category == sleeve.category
        )

        avg_spread = (
            sum(item.spread_bps for item in sleeve_instruments) / len(sleeve_instruments)
            if sleeve_instruments
            else 0.0
        )
        microstructure = max(0.0, min(1.0, 1.0 - avg_spread / 100.0 + abs(raw.bid_ask_imbalance) * 0.3))
        vols = [item.volatility for item in sleeve_instruments]
        vol_pct = max(vols) if vols else 0.5

        return StrategyMarketContext(
            sleeve=SleeveStrategyContext(
                sleeve_id=sleeve.sleeve_id,
                category=sleeve.category,
                instruments=sleeve_instruments,
                risk_budget_remaining=sleeve.risk_budget_remaining,
            ),
            regime=_infer_regime(raw),
            session_active=True,
            microstructure_score=microstructure,
            volatility_percentile=min(1.0, vol_pct),
            asset_class=self.asset_class,
            news_locked_instrument_ids=news_locked_instrument_ids or frozenset(),
        )


class EquityRegimeAdapter(RegimeAdapter):
    """Session-based equity markets — regime from momentum and macro vol."""

    asset_class = "equity"

    def build_context(
        self,
        raw: RawMarketSnapshot,
        sleeve: SleeveStrategyContext,
        *,
        news_locked_instrument_ids: frozenset[int] | None = None,
    ) -> StrategyMarketContext:
        sleeve_instruments = tuple(
            item for item in raw.instruments if item.category == sleeve.category
        )
        regime = _infer_regime(raw)
        if raw.vix_level is not None and raw.vix_level >= 25:
            regime = MarketRegime.HIGH_VOL

        microstructure = 0.3 if raw.session_active else 0.0
        vol_pct = min(1.0, (raw.vix_level or 15.0) / 40.0)

        return StrategyMarketContext(
            sleeve=SleeveStrategyContext(
                sleeve_id=sleeve.sleeve_id,
                category=sleeve.category,
                instruments=sleeve_instruments,
                risk_budget_remaining=sleeve.risk_budget_remaining,
            ),
            regime=regime,
            session_active=raw.session_active,
            microstructure_score=microstructure,
            volatility_percentile=vol_pct,
            asset_class=self.asset_class,
            news_locked_instrument_ids=news_locked_instrument_ids or frozenset(),
        )
