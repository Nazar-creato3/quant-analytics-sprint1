"""Prediction + Risk stack context builder (Prompt 30).

Wires market data → quant_math → RegimeEngine + FactorEngine → MarketGraph
→ ForecastEngine → RiskEngine for offline validation and DealIntent gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from app.domain.profile import ProfileRead
from app.domain.sleeve import SleeveRead
from app.services.approval.models import MarketContext
from app.services.control_fabric.risk_engine import RiskEngine, get_risk_engine
from app.services.control_fabric.risk_types import RiskBudgetContext, RiskEngineInput
from app.services.factor.engine import FactorEngine
from app.services.factor.types import ALL_FACTORS, FactorName
from app.services.forecast.engine import ForecastEngine
from app.services.forecast.types import ForecastInputBundle, InstrumentForecast
from app.services.integration.historical_data import rolling_indicators
from app.services.integration.marginal_risk_gate import enrich_market_context_with_marginal_risk
from app.services.integration.types import HistoricalBar, VenueConfig
from app.services.macro.sector_seed import sector_for_symbol
from app.services.market_graph.builder import (
    average_intra_sector_correlation,
    build_correlation_edges,
    find_correlated_cluster,
    returns_from_closes,
)
from app.services.market_graph.types import GraphEdgeRow
from app.services.quant_math import correlation
from app.services.regime.engine import RegimeEngine
from app.services.regime.features import prices_to_returns
from app.services.regime.types import RegimeClassificationResult

REGIME_TO_MARKET: dict[str, str] = {
    "bullish_trend": "trend_up",
    "bearish_trend": "trend_down",
    "choppy_range": "range",
    "high_volatility_shock": "high_vol",
    "liquidity_drought": "high_vol",
    "macro_uncertainty": "high_vol",
}

DEFAULT_CORRELATION_THRESHOLD = 0.7
MIN_HISTORY_BARS = 25


@dataclass(frozen=True, slots=True)
class PredictionRiskStackContext:
    """Mandatory prediction + risk context for ApprovalPolicyEngine / AntiLossGuard."""

    market_context: MarketContext
    risk_inputs: RiskEngineInput
    forecast: InstrumentForecast
    regime_result: RegimeClassificationResult
    correlation_edges: tuple[GraphEdgeRow, ...]
    max_correlation_with_portfolio: float
    factor_exposures: dict[FactorName, float]


class PredictionRiskStack:
    """Build end-to-end prediction/risk context from historical bars."""

    def __init__(
        self,
        *,
        regime_engine: RegimeEngine | None = None,
        factor_engine: FactorEngine | None = None,
        forecast_engine: ForecastEngine | None = None,
        risk_engine: RiskEngine | None = None,
        correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD,
    ) -> None:
        self._regime_engine = regime_engine or RegimeEngine()
        self._factor_engine = factor_engine or FactorEngine()
        self._forecast_engine = forecast_engine or ForecastEngine(
            regime_engine=self._regime_engine,
        )
        self._risk_engine = risk_engine or get_risk_engine()
        self._correlation_threshold = correlation_threshold

    def build_at_index(
        self,
        bars_by_instrument: Mapping[int, Sequence[HistoricalBar]],
        *,
        target: VenueConfig,
        index: int,
        profile: ProfileRead,
        sleeve: SleeveRead,
        profile_drawdown_pct: float = 0.0,
        profile_daily_loss_abs: Decimal | None = None,
        proposed_delta_weight: float | None = None,
    ) -> PredictionRiskStackContext:
        """Compose stack context at a historical bar index."""
        target_bars = list(bars_by_instrument.get(target.instrument_id, ()))
        if index >= len(target_bars):
            raise IndexError(f"index {index} out of range for instrument {target.instrument_id}")

        window_bars = target_bars[: index + 1]
        prices = [bar.close for bar in window_bars]
        volumes = [bar.volume for bar in window_bars]
        highs = [bar.high for bar in window_bars]
        lows = [bar.low for bar in window_bars]
        closes = [bar.close for bar in window_bars]

        indicators = rolling_indicators(closes, highs, lows)
        spread_bps = indicators["spread_bps"]

        returns_by_instrument = self._returns_by_instrument(bars_by_instrument, index)
        sector_by_instrument = self._sector_by_instrument(bars_by_instrument)
        correlation_edges = tuple(
            build_correlation_edges(returns_by_instrument)
        )
        correlation_cluster = self._correlation_cluster_score(
            target.instrument_id,
            sector_by_instrument,
            correlation_edges,
        )
        max_correlation = self._max_pair_correlation(
            target.instrument_id,
            returns_by_instrument,
        )

        regime_result = self._regime_engine.classify_instrument(
            prices,
            volumes,
            spread_bps=spread_bps,
            correlation_cluster=correlation_cluster,
        )
        dominant_regime = regime_result.dominant_regime
        market_regime = REGIME_TO_MARKET.get(dominant_regime, dominant_regime)

        prior_weights = self._prior_correlation_weights(
            target.instrument_id,
            correlation_edges,
            lookback=min(10, index),
        )
        current_weights = self._correlation_weights_for_instrument(
            target.instrument_id,
            correlation_edges,
        )

        forecast = self._forecast_engine.compute_from_inputs(
            ForecastInputBundle(
                instrument_id=target.instrument_id,
                prices=prices,
                volumes=volumes,
                spread_bps=spread_bps,
                regime_result=regime_result,
                correlation_edge_weights=current_weights,
                prior_correlation_edge_weights=prior_weights,
            )
        )

        factor_exposures = self._latest_factor_exposures(
            target.instrument_id,
            window_bars,
            returns_by_instrument,
        )
        history_returns = prices_to_returns(prices)
        overnight_returns = self._overnight_returns(window_bars)

        risk_inputs = RiskEngineInput(
            instrument_id=target.instrument_id,
            returns_by_instrument=returns_by_instrument,
            prices_by_instrument={
                instrument_id: [bar.close for bar in bars[: index + 1]]
                for instrument_id, bars in bars_by_instrument.items()
                if index < len(bars)
            },
            overnight_returns_by_instrument={
                target.instrument_id: overnight_returns,
            },
            factor_exposures={
                target.instrument_id: factor_exposures,
            },
            sector_by_instrument=sector_by_instrument,
            correlation_edges=correlation_edges,
            tail_risk_score=forecast.signals.tail_risk_score,
            liquidity_risk_score=forecast.signals.liquidity_deterioration_score,
            asset_category=target.category,
        )

        risk_budget = RiskBudgetContext(
            diversification_policy=profile.diversification_policy or {},
            max_drawdown_pct=float(profile.max_drawdown_pct),
            sleeve_risk_budget=sleeve.risk_budget,
            profile_max_daily_loss=profile.max_daily_loss_abs,
        )
        risk_assessment = self._risk_engine.assess(risk_inputs, risk_budget)

        market_context = MarketContext(
            instrument_volatility=indicators["volatility"],
            instrument_spread_bps=spread_bps,
            instrument_category=target.category,
            max_correlation_with_portfolio=max_correlation,
            market_regime=market_regime,
            profile_drawdown_pct=profile_drawdown_pct,
            profile_daily_loss_abs=profile_daily_loss_abs or Decimal("0"),
            sleeve_status=sleeve.status,
            sleeve_risk_budget_remaining=sleeve.risk_budget,
            dominant_regime=dominant_regime,
            regime_confidence=regime_result.confidence,
            forecast_confidence=forecast.confidence,
            forecast_composite_risk_score=forecast.composite_risk_score,
            tail_risk_score=forecast.signals.tail_risk_score,
            risk_engine_breach_count=len(risk_assessment.breached),
            risk_flags=tuple(forecast.risk_flags),
            remaining_risk_budget_var=float(sleeve.risk_budget) if sleeve.risk_budget else None,
        )
        if proposed_delta_weight is not None and proposed_delta_weight > 0:
            market_context = enrich_market_context_with_marginal_risk(
                market_context,
                bars_by_instrument=bars_by_instrument,
                target=target,
                index=index,
                profile=profile,
                sleeve=sleeve,
                delta_weight=proposed_delta_weight,
                correlation_edges=correlation_edges,
            )

        return PredictionRiskStackContext(
            market_context=market_context,
            risk_inputs=risk_inputs,
            forecast=forecast,
            regime_result=regime_result,
            correlation_edges=correlation_edges,
            max_correlation_with_portfolio=max_correlation,
            factor_exposures=factor_exposures,
        )

    @staticmethod
    def _returns_by_instrument(
        bars_by_instrument: Mapping[int, Sequence[HistoricalBar]],
        index: int,
    ) -> dict[int, list[float]]:
        returns: dict[int, list[float]] = {}
        for instrument_id, bars in bars_by_instrument.items():
            if index >= len(bars):
                continue
            closes = [bar.close for bar in bars[: index + 1]]
            series = returns_from_closes(closes)
            if series:
                returns[instrument_id] = series
        return returns

    @staticmethod
    def _sector_by_instrument(
        bars_by_instrument: Mapping[int, Sequence[HistoricalBar]],
    ) -> dict[int, str]:
        sectors: dict[int, str] = {}
        for instrument_id, bars in bars_by_instrument.items():
            if not bars:
                continue
            mapping = sector_for_symbol(bars[0].symbol)
            sectors[instrument_id] = mapping[0] if mapping else "unknown"
        return sectors

    def _correlation_cluster_score(
        self,
        instrument_id: int,
        sector_by_instrument: Mapping[int, str],
        edges: Sequence[GraphEdgeRow],
    ) -> float:
        sector = sector_by_instrument.get(instrument_id, "unknown")
        peers = [
            peer_id
            for peer_id, peer_sector in sector_by_instrument.items()
            if peer_sector == sector
        ]
        if len(peers) < 2:
            cluster = find_correlated_cluster(
                instrument_id,
                edges,
                threshold=self._correlation_threshold,
            )
            return min(1.0, len(cluster) / 10.0)
        return average_intra_sector_correlation(peers, edges)

    @staticmethod
    def _max_pair_correlation(
        instrument_id: int,
        returns_by_instrument: Mapping[int, Sequence[float]],
    ) -> float:
        target_returns = returns_by_instrument.get(instrument_id)
        if not target_returns:
            return 0.0
        max_corr = 0.0
        for peer_id, peer_returns in returns_by_instrument.items():
            if peer_id == instrument_id:
                continue
            length = min(len(target_returns), len(peer_returns))
            if length < 2:
                continue
            pair_corr = abs(
                correlation(
                    list(target_returns[-length:]),
                    list(peer_returns[-length:]),
                )
            )
            max_corr = max(max_corr, pair_corr)
        return min(1.0, max_corr)

    @staticmethod
    def _correlation_weights_for_instrument(
        instrument_id: int,
        edges: Sequence[GraphEdgeRow],
    ) -> list[float]:
        from app.services.market_graph.nodes import instrument_node

        seed = instrument_node(instrument_id)
        weights: list[float] = []
        for edge in edges:
            if edge.from_node == seed:
                weights.append(abs(edge.weight))
        return weights

    @staticmethod
    def _prior_correlation_weights(
        instrument_id: int,
        edges: Sequence[GraphEdgeRow],
        *,
        lookback: int,
    ) -> list[float]:
        weights = PredictionRiskStack._correlation_weights_for_instrument(
            instrument_id,
            edges,
        )
        if lookback <= 0 or not weights:
            return weights
        trimmed = weights[-lookback:]
        return trimmed if trimmed else weights

    def _latest_factor_exposures(
        self,
        instrument_id: int,
        bars: Sequence[HistoricalBar],
        returns_by_instrument: Mapping[int, Sequence[float]],
    ) -> dict[FactorName, float]:
        instrument_returns = returns_by_instrument.get(instrument_id, [])
        if len(instrument_returns) < MIN_HISTORY_BARS:
            return {factor: 0.0 for factor in ALL_FACTORS}

        timestamps = [bar.timestamp for bar in bars]
        factor_returns = self._synthetic_factor_returns(
            instrument_returns,
            returns_by_instrument,
            sector_by_instrument=self._sector_by_instrument({instrument_id: bars}),
            instrument_id=instrument_id,
        )
        rows = self._factor_engine.estimate_from_series(
            instrument_id=instrument_id,
            timestamps=timestamps[1:],
            instrument_returns=instrument_returns,
            factor_returns=factor_returns,
        )
        if not rows:
            return {factor: 0.0 for factor in ALL_FACTORS}

        latest_time = max(row.time for row in rows)
        return {
            row.factor_name: row.beta
            for row in rows
            if row.time == latest_time
        }

    @staticmethod
    def _synthetic_factor_returns(
        instrument_returns: Sequence[float],
        returns_by_instrument: Mapping[int, Sequence[float]],
        *,
        sector_by_instrument: Mapping[int, str],
        instrument_id: int,
    ) -> dict[FactorName, list[float]]:
        length = len(instrument_returns)
        zeros = [0.0] * length
        market = list(instrument_returns)
        if len(returns_by_instrument) > 1:
            market = []
            for index in range(length):
                values = [
                    series[index]
                    for series in returns_by_instrument.values()
                    if index < len(series)
                ]
                market.append(sum(values) / len(values) if values else 0.0)

        sector = sector_by_instrument.get(instrument_id, "unknown")
        sector_values: list[float] = []
        for index in range(length):
            peers = [
                series[index]
                for peer_id, series in returns_by_instrument.items()
                if peer_id != instrument_id
                and sector_by_instrument.get(peer_id) == sector
                and index < len(series)
            ]
            sector_values.append(
                sum(peers) / len(peers) if peers else market[index] if index < len(market) else 0.0
            )

        return {
            FactorName.MARKET_BETA: market,
            FactorName.SECTOR_FACTOR: sector_values,
            FactorName.MOMENTUM: [
                sum(instrument_returns[max(0, index - 4) : index + 1])
                for index in range(length)
            ],
            FactorName.VALUE: zeros,
            FactorName.GROWTH: zeros,
            FactorName.VOLATILITY_FACTOR: [
                abs(value) for value in instrument_returns
            ],
            FactorName.RATES_SENSITIVITY: zeros,
            FactorName.FX_SENSITIVITY: zeros,
            FactorName.COMMODITY_SENSITIVITY: zeros,
            FactorName.MACRO_SHOCK_SENSITIVITY: zeros,
        }

    @staticmethod
    def _overnight_returns(bars: Sequence[HistoricalBar]) -> list[float]:
        if len(bars) < 2:
            return []
        overnight: list[float] = []
        for index in range(1, len(bars)):
            previous_close = bars[index - 1].close
            current_open = bars[index].open
            if previous_close <= 0:
                overnight.append(0.0)
            else:
                overnight.append((current_open - previous_close) / previous_close)
        return overnight
