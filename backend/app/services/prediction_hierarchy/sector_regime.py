"""Sector Regime Engine — aggregation + rotation scoring (Prompt 31)."""
from __future__ import annotations

from typing import Mapping, Sequence

from app.services.regime.engine import RegimeEngine
from app.services.regime.features import (
    aggregate_sector_prices,
    prices_to_returns,
    sector_return_series,
)
from app.services.regime.types import InstrumentSeries, RegimeClassificationResult
from app.services.prediction_hierarchy.types import (
    SectorRegimeContext,
    SectorRotationFlag,
    SectorRotationScore,
)

WEAK_SECTOR_REGIMES = frozenset(
    {
        "bearish_trend",
        "high_volatility_shock",
        "liquidity_drought",
        "macro_uncertainty",
    }
)

# Trading-day approximations for horizons
HORIZON_1W = 5
HORIZON_1M = 21
HORIZON_3M = 63

SECTOR_CONFIDENCE_PENALTY = 0.25


def _relative_strength(
    sector_returns: Sequence[float],
    market_returns: Sequence[float],
    window: int,
) -> float:
    """Sector return minus market return over rolling window."""
    if not sector_returns or not market_returns:
        return 0.0
    length = min(window, len(sector_returns), len(market_returns))
    if length < 2:
        return 0.0
    sector_cum = sum(sector_returns[-length:])
    market_cum = sum(market_returns[-length:])
    return sector_cum - market_cum


def _classify_rotation(
    score_1w: float,
    score_1m: float,
    score_3m: float,
) -> SectorRotationFlag:
    """Classify sector rotation state from multi-horizon relative strength."""
    positive = sum(1 for value in (score_1w, score_1m, score_3m) if value > 0.001)
    negative = sum(1 for value in (score_1w, score_1m, score_3m) if value < -0.001)

    if positive >= 2 and score_1w > 0:
        return SectorRotationFlag.SECTORS_STRENGTHENING
    if negative >= 2 and score_1w < 0:
        return SectorRotationFlag.SECTORS_WEAKENING
    if (score_1w > 0 and score_3m < 0) or (score_1w < 0 and score_3m > 0):
        return SectorRotationFlag.ROTATION_IN_PROGRESS
    return SectorRotationFlag.NEUTRAL


class SectorRegimeEngine:
    """Extend RegimeEngine with sector aggregation and rotation scoring."""

    def __init__(self, *, regime_engine: RegimeEngine | None = None) -> None:
        self._regime_engine = regime_engine or RegimeEngine()

    def classify_sector_regime(
        self,
        sector: str,
        instruments: dict[int, InstrumentSeries],
        *,
        market_prices: Sequence[float] | None = None,
    ) -> SectorRegimeContext:
        """Classify sector regime with momentum vs market."""
        regime = self._regime_engine.classify_sector(instruments)
        sector_prices = aggregate_sector_prices(instruments)
        sector_returns = prices_to_returns(sector_prices)

        if market_prices:
            market_returns = prices_to_returns(list(market_prices))
        else:
            market_returns = sector_returns

        momentum = _relative_strength(sector_returns, market_returns, HORIZON_1M)
        rotation = self.compute_rotation_score(sector, sector_returns, market_returns)
        return SectorRegimeContext(
            sector=sector,
            regime=regime,
            rotation=rotation,
            sector_momentum=momentum,
        )

    def compute_rotation_score(
        self,
        sector: str,
        sector_returns: Sequence[float],
        market_returns: Sequence[float],
    ) -> SectorRotationScore:
        score_1w = _relative_strength(sector_returns, market_returns, HORIZON_1W)
        score_1m = _relative_strength(sector_returns, market_returns, HORIZON_1M)
        score_3m = _relative_strength(sector_returns, market_returns, HORIZON_3M)
        composite = 0.5 * score_1m + 0.3 * score_3m + 0.2 * score_1w
        flag = _classify_rotation(score_1w, score_1m, score_3m)
        return SectorRotationScore(
            sector=sector,
            score_1w=round(score_1w, 6),
            score_1m=round(score_1m, 6),
            score_3m=round(score_3m, 6),
            composite_score=round(composite, 6),
            rotation_flag=flag,
        )

    def rank_sectors(
        self,
        sector_returns: Mapping[str, Sequence[float]],
        market_returns: Sequence[float],
    ) -> list[SectorRotationScore]:
        """Rank all sectors by composite relative strength."""
        scores = [
            self.compute_rotation_score(sector, returns, market_returns)
            for sector, returns in sector_returns.items()
        ]
        ranked = sorted(scores, key=lambda item: item.composite_score, reverse=True)
        return [
            SectorRotationScore(
                sector=item.sector,
                score_1w=item.score_1w,
                score_1m=item.score_1m,
                score_3m=item.score_3m,
                composite_score=item.composite_score,
                rotation_flag=item.rotation_flag,
                rank=index + 1,
            )
            for index, item in enumerate(ranked)
        ]

    @staticmethod
    def apply_sector_confidence_penalty(
        ticker_confidence: float,
        sector_regime: RegimeClassificationResult,
        *,
        sector_rotation: SectorRotationScore | None = None,
    ) -> float:
        """Reduce ticker confidence (not direction) when sector context is weak."""
        confidence = ticker_confidence
        if sector_regime.dominant_regime in WEAK_SECTOR_REGIMES:
            confidence *= 1.0 - SECTOR_CONFIDENCE_PENALTY
        if sector_rotation and sector_rotation.rotation_flag == SectorRotationFlag.SECTORS_WEAKENING:
            confidence *= 1.0 - SECTOR_CONFIDENCE_PENALTY * 0.5
        return max(0.0, min(1.0, confidence))

    def build_sector_instruments(
        self,
        all_instruments: dict[int, InstrumentSeries],
        sector_by_instrument: Mapping[int, str],
        target_sector: str,
    ) -> dict[int, InstrumentSeries]:
        return {
            instrument_id: series
            for instrument_id, series in all_instruments.items()
            if sector_by_instrument.get(instrument_id) == target_sector
        }

    @staticmethod
    def aggregate_market_prices(
        sector_instruments: Mapping[str, dict[int, InstrumentSeries]],
    ) -> list[float]:
        """Equal-weight market aggregate from all sector instruments."""
        all_prices: list[list[float]] = []
        for instruments in sector_instruments.values():
            prices = aggregate_sector_prices(instruments)
            if prices:
                all_prices.append(prices)
        if not all_prices:
            return []
        min_len = min(len(p) for p in all_prices)
        return [
            sum(prices[index] for prices in all_prices) / len(all_prices)
            for index in range(min_len)
        ]

    @staticmethod
    def sector_return_map(
        sector_instruments: Mapping[str, dict[int, InstrumentSeries]],
    ) -> dict[str, list[float]]:
        result: dict[str, list[float]] = {}
        for sector, instruments in sector_instruments.items():
            prices = aggregate_sector_prices(instruments)
            returns = sector_return_series(instruments) if instruments else prices_to_returns(prices)
            if returns:
                result[sector] = returns
        return result
