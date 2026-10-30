"""Global/macro analysis layer for Forecast section — correlation matrix, regime map, factor rotation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.prediction_hierarchy.global_regime import (
    GlobalMacroRegimeEngine,
    MacroIndicatorSnapshot,
)
from app.services.prediction_hierarchy.sector_regime import SectorRegimeEngine
from app.services.regime.engine import RegimeEngine

logger = get_logger(__name__)

DEFAULT_UNIVERSE = ("SPY", "QQQ", "BTC-USD", "CL=F", "GC=F", "^GSPC")

# ETF ↔ tracked index — regime and correlation must agree (see AUDIT.md bug 3/4).
ETF_INDEX_ALIASES: dict[str, str] = {
    "SPY": "^GSPC",
    "^GSPC": "SPY",
    "QQQ": "^IXIC",
    "^IXIC": "QQQ",
    "DIA": "^DJI",
    "^DJI": "DIA",
}
REGIME_LABELS_RU = {
    "bullish_trend": "тренд вверх",
    "bearish_trend": "тренд вниз",
    "choppy_range": "боковик",
    "high_volatility_shock": "высокая волатильность",
    "risk_on": "risk-on",
    "risk_off": "risk-off",
    "macro_uncertainty": "макро-неопределённость",
}


@dataclass(frozen=True, slots=True)
class RegimeMapEntry:
    symbol: str
    label: str
    dominant_regime: str
    dominant_regime_ru: str
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "label": self.label,
            "dominant_regime": self.dominant_regime,
            "dominant_regime_ru": self.dominant_regime_ru,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class FactorRotationEntry:
    factor: str
    score: float
    rank: int
    direction: str  # "outperform" | "underperform" | "neutral"

    def to_dict(self) -> dict[str, object]:
        return {
            "factor": self.factor,
            "score": self.score,
            "rank": self.rank,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class GlobalMacroView:
    correlation_matrix: dict[str, dict[str, float]]
    correlation_symbols: tuple[str, ...]
    regime_map: tuple[RegimeMapEntry, ...]
    factor_rotation: tuple[FactorRotationEntry, ...]
    as_of: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "correlation_matrix": self.correlation_matrix,
            "correlation_symbols": list(self.correlation_symbols),
            "regime_map": [e.to_dict() for e in self.regime_map],
            "factor_rotation": [e.to_dict() for e in self.factor_rotation],
            "as_of": self.as_of,
        }


def _returns_from_dated_closes(
    dated_closes: dict[str, float],
) -> dict[str, float]:
    """Simple close-to-close returns keyed by date string."""
    sorted_dates = sorted(dated_closes.keys())
    out: dict[str, float] = {}
    for i in range(1, len(sorted_dates)):
        prev_date, curr_date = sorted_dates[i - 1], sorted_dates[i]
        prev_close = dated_closes[prev_date]
        curr_close = dated_closes[curr_date]
        if prev_close > 0:
            out[curr_date] = (curr_close - prev_close) / prev_close
    return out


def _align_dated_returns(
    series_by_symbol: dict[str, dict[str, float]],
) -> dict[str, list[float]]:
    """Join return series on shared calendar dates (not tail length)."""
    if not series_by_symbol:
        return {}
    common_dates: set[str] | None = None
    for rets in series_by_symbol.values():
        dates = set(rets.keys())
        common_dates = dates if common_dates is None else common_dates & dates
    if not common_dates:
        return {}

    ordered = sorted(common_dates)
    return {
        sym: [rets[d] for d in ordered if d in rets]
        for sym, rets in series_by_symbol.items()
        if len([d for d in ordered if d in rets]) >= 10
    }


def _compute_correlation_matrix(
    symbol_returns: dict[str, list[float]],
) -> tuple[dict[str, dict[str, float]], tuple[str, ...]]:
    symbols = tuple(s for s, r in symbol_returns.items() if len(r) >= 10)
    if len(symbols) < 2:
        return {}, symbols

    matrix: dict[str, dict[str, float]] = {}
    for s1 in symbols:
        matrix[s1] = {}
        for s2 in symbols:
            if s1 == s2:
                matrix[s1][s2] = 1.0
            else:
                r1 = np.array(symbol_returns[s1])
                r2 = np.array(symbol_returns[s2])
                min_len = min(len(r1), len(r2))
                r1 = r1[-min_len:]
                r2 = r2[-min_len:]
                if np.std(r1) < 1e-9 or np.std(r2) < 1e-9:
                    matrix[s1][s2] = 0.0
                else:
                    matrix[s1][s2] = round(float(np.corrcoef(r1, r2)[0, 1]), 3)
    return matrix, symbols


def _factor_rotation_from_exposures(
    factor_scores: dict[str, float],
) -> tuple[FactorRotationEntry, ...]:
    if not factor_scores:
        return ()
    sorted_factors = sorted(factor_scores.items(), key=lambda x: -abs(x[1]))
    entries: list[FactorRotationEntry] = []
    for rank, (factor, score) in enumerate(sorted_factors[:8], start=1):
        if score > 0.3:
            direction = "outperform"
        elif score < -0.3:
            direction = "underperform"
        else:
            direction = "neutral"
        entries.append(
            FactorRotationEntry(
                factor=factor.replace("_", " "),
                score=round(score, 3),
                rank=rank,
                direction=direction,
            )
        )
    return tuple(entries)


class GlobalMacroViewBuilder:
    """Build cross-asset correlation, multi-market regime map, factor rotation."""

    def __init__(self) -> None:
        self._regime_engine = RegimeEngine()
        self._sector_engine = SectorRegimeEngine()
        self._global_engine = GlobalMacroRegimeEngine()

    async def build(
        self,
        db: AsyncSession,
        *,
        symbols: Sequence[str] | None = None,
        factor_exposures: dict[str, float] | None = None,
        macro_indicators: dict[str, float] | None = None,
    ) -> GlobalMacroView:
        from app.services.instrument.resolver import resolve_or_create_instrument
        from app.services.market_data.series_loader import load_forecast_price_series

        universe = tuple(symbols or DEFAULT_UNIVERSE)
        dated_closes_by_symbol: dict[str, dict[str, float]] = {}
        symbol_prices: dict[str, list[float]] = {}
        symbol_volumes: dict[str, list[float]] = {}
        regime_by_symbol: dict[str, RegimeMapEntry] = {}

        for sym in universe:
            try:
                instrument = await resolve_or_create_instrument(db, sym)
                prices, volumes, _src = await load_forecast_price_series(
                    db, instrument.id, instrument.symbol, persist=False
                )
                if len(prices) >= 10:
                    symbol_prices[sym] = prices
                    symbol_volumes[sym] = volumes
                    # Load dated closes for calendar alignment
                    dated = await _load_dated_closes(db, instrument.id)
                    if dated:
                        dated_closes_by_symbol[sym] = dated
            except Exception as exc:
                logger.debug("Global macro skip symbol", symbol=sym, error=str(exc))

        # Date-aligned returns for correlation matrix
        dated_returns = {
            sym: _returns_from_dated_closes(closes)
            for sym, closes in dated_closes_by_symbol.items()
        }
        aligned_returns = _align_dated_returns(dated_returns)
        if not aligned_returns:
            aligned_returns = {
                sym: [
                    (prices[i] - prices[i - 1]) / max(prices[i - 1], 1e-9)
                    for i in range(1, len(prices))
                ]
                for sym, prices in symbol_prices.items()
            }

        for sym, prices in symbol_prices.items():
            volumes = symbol_volumes.get(sym)
            regime = self._regime_engine.classify_instrument(prices, volumes)
            regime_by_symbol[sym] = RegimeMapEntry(
                symbol=sym,
                label=sym,
                dominant_regime=regime.dominant_regime,
                dominant_regime_ru=REGIME_LABELS_RU.get(
                    regime.dominant_regime, regime.dominant_regime
                ),
                confidence=min(0.95, regime.confidence),
            )

        # Mirror regime for ETF/index alias pairs on shared aligned data
        for etf, index in ETF_INDEX_ALIASES.items():
            if etf not in regime_by_symbol or index not in regime_by_symbol:
                continue
            if etf >= index:
                continue
            primary = etf if len(symbol_prices.get(etf, [])) >= len(symbol_prices.get(index, [])) else index
            canonical = regime_by_symbol[primary]
            for alias in (etf, index):
                regime_by_symbol[alias] = RegimeMapEntry(
                    symbol=alias,
                    label=alias,
                    dominant_regime=canonical.dominant_regime,
                    dominant_regime_ru=canonical.dominant_regime_ru,
                    confidence=canonical.confidence,
                )

        regime_entries = [regime_by_symbol[s] for s in universe if s in regime_by_symbol]
        matrix, corr_symbols = _compute_correlation_matrix(aligned_returns)
        factor_rotation = _factor_rotation_from_exposures(factor_exposures or {})

        from datetime import datetime, timezone

        return GlobalMacroView(
            correlation_matrix=matrix,
            correlation_symbols=corr_symbols,
            regime_map=tuple(regime_entries),
            factor_rotation=factor_rotation,
            as_of=datetime.now(timezone.utc).isoformat(),
        )


_builder = GlobalMacroViewBuilder()


def get_global_macro_view_builder() -> GlobalMacroViewBuilder:
    return _builder


async def _load_dated_closes(db: AsyncSession, instrument_id: int) -> dict[str, float]:
    """Load daily closes keyed by ISO date for calendar alignment."""
    from sqlalchemy import select

    from app.domain.market_data import MarketOhlcvORM

    stmt = (
        select(MarketOhlcvORM)
        .where(
            MarketOhlcvORM.instrument_id == instrument_id,
            MarketOhlcvORM.timeframe == "1d",
        )
        .order_by(MarketOhlcvORM.time.asc())
        .limit(120)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    dated: dict[str, float] = {}
    for row in rows:
        if row.close is None or row.time is None:
            continue
        key = row.time.date().isoformat()
        dated[key] = float(row.close)
    return dated
