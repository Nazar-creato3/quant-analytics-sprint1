"""ForecastEngine — probabilistic ensemble map per instrument (Prompt 22).

This engine aggregates regime, tail-risk, liquidity, correlation, and event signals.
It does NOT produce a price prediction — only a probability map for risk and regime context.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.domain.instrument import InstrumentORM
from app.domain.market_data import MarketOhlcvORM
from app.services.event_risk.layer import EventRiskLayer, get_event_risk_layer
from app.services.forecast.aggregation import aggregate_forecast
from app.services.forecast.signals import (
    build_returns,
    compute_correlation_shift_score,
    compute_event_impact_score,
    compute_liquidity_deterioration_score,
    compute_short_term_momentum,
    compute_tail_risk_score,
    compute_volatility_expansion_probability,
    correlation_weights_for_instrument,
)
from app.services.forecast.types import ForecastInputBundle, ForecastSignals, InstrumentForecast
from app.services.liquidity.monitor import LiquidityMonitor, get_liquidity_monitor
from app.services.market_graph.repository import MarketGraphRepository
from app.services.market_graph.types import EdgeType
from app.services.regime.engine import RegimeEngine

class ForecastEngine:
    """Aggregate ensemble signals into a probabilistic per-instrument forecast map."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        regime_engine: RegimeEngine | None = None,
        liquidity_monitor: LiquidityMonitor | None = None,
        event_risk_layer: EventRiskLayer | None = None,
        market_graph_repository: MarketGraphRepository | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._regime_engine = regime_engine or RegimeEngine()
        self._liquidity_monitor = liquidity_monitor or get_liquidity_monitor()
        self._event_risk_layer = event_risk_layer or get_event_risk_layer()
        self._market_graph_repository = market_graph_repository or MarketGraphRepository()

    def compute_from_inputs(self, bundle: ForecastInputBundle) -> InstrumentForecast:
        """Pure composition path for tests and offline replay."""
        regime_result = bundle.regime_result or self._regime_engine.classify_instrument(
            bundle.prices,
            bundle.volumes,
            spread_bps=bundle.spread_bps,
        )
        returns = build_returns(bundle.prices, bundle.returns)

        momentum_strength, momentum_direction = compute_short_term_momentum(
            bundle.prices,
            bundle.volumes,
        )
        tail_risk = compute_tail_risk_score(
            returns,
            alpha=self._settings.FORECAST_TAIL_RISK_ALPHA,
            normalization_scale=self._settings.FORECAST_TAIL_RISK_NORMALIZATION,
        )
        vol_expansion = compute_volatility_expansion_probability(
            returns,
            window=self._settings.FORECAST_VOL_WINDOW,
            trend_periods=self._settings.FORECAST_VOL_TREND_PERIODS,
        )
        correlation_shift = compute_correlation_shift_score(
            bundle.correlation_edge_weights,
            bundle.prior_correlation_edge_weights,
        )
        liquidity_deterioration = compute_liquidity_deterioration_score(
            liquidity_score=bundle.liquidity_score,
            prior_liquidity_score=bundle.prior_liquidity_score,
            spread_bps=bundle.spread_bps,
            prior_spread_bps=bundle.prior_spread_bps,
            depth_ratio=bundle.depth_ratio,
            prior_depth_ratio=bundle.prior_depth_ratio,
            max_spread_bps=self._settings.LIQUIDITY_MAX_SPREAD_BPS,
        )
        event_impact = min(1.0, max(0.0, float(bundle.event_impact_score)))

        signals = ForecastSignals(
            short_term_momentum=momentum_strength,
            momentum_direction=momentum_direction,
            tail_risk_score=tail_risk,
            volatility_expansion_probability=vol_expansion,
            correlation_shift_score=correlation_shift,
            liquidity_deterioration_score=liquidity_deterioration,
            event_impact_score=event_impact,
        )
        return aggregate_forecast(
            instrument_id=bundle.instrument_id,
            regime_distribution=dict(regime_result.distribution),
            regime_confidence=regime_result.confidence,
            signals=signals,
            risk_flag_threshold=self._settings.FORECAST_RISK_FLAG_THRESHOLD,
            elevated_uncertainty_threshold=self._settings.FORECAST_ELEVATED_UNCERTAINTY_THRESHOLD,
        )

    async def forecast_instrument(
        self,
        session: AsyncSession,
        instrument_id: int,
        *,
        as_of: datetime | None = None,
    ) -> InstrumentForecast | None:
        """Load live inputs and produce a probabilistic map for one instrument."""
        instrument = await session.get(InstrumentORM, instrument_id)
        if instrument is None:
            return None

        prices, volumes = await self._load_price_series(session, instrument_id, as_of=as_of)
        if len(prices) < 10:
            return None

        spread_bps, depth_ratio, prior_spread_bps, prior_depth_ratio, liquidity_score, prior_liquidity = (
            await self._load_liquidity_features(session, instrument, as_of=as_of)
        )
        correlation_weights, prior_correlation_weights = await self._load_correlation_weights(
            session,
            instrument_id,
        )
        event_score = await self._load_event_impact_score(
            session,
            instrument,
            as_of=as_of,
        )

        regime_result = self._regime_engine.classify_instrument(
            prices,
            volumes,
            spread_bps=spread_bps,
        )
        return self.compute_from_inputs(
            ForecastInputBundle(
                instrument_id=instrument_id,
                prices=prices,
                volumes=volumes,
                spread_bps=spread_bps,
                regime_result=regime_result,
                correlation_edge_weights=correlation_weights,
                prior_correlation_edge_weights=prior_correlation_weights,
                liquidity_score=liquidity_score,
                prior_liquidity_score=prior_liquidity,
                depth_ratio=depth_ratio,
                prior_depth_ratio=prior_depth_ratio,
                prior_spread_bps=prior_spread_bps,
                event_impact_score=event_score,
            )
        )

    async def _load_price_series(
        self,
        session: AsyncSession,
        instrument_id: int,
        *,
        as_of: datetime | None = None,
    ) -> tuple[list[float], list[float]]:
        instrument = await session.get(InstrumentORM, instrument_id)
        if instrument is not None:
            from app.services.market_data.series_loader import load_forecast_price_series

            prices, volumes, _source = await load_forecast_price_series(
                session,
                instrument_id,
                instrument.symbol,
                persist=True,
                as_of=as_of,
            )
            if len(prices) >= 10:
                return prices, volumes

        filters = [
            MarketOhlcvORM.instrument_id == instrument_id,
            MarketOhlcvORM.timeframe == "1d",
        ]
        if as_of is not None:
            from datetime import timezone

            cutoff = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
            filters.append(MarketOhlcvORM.time <= cutoff)
        stmt = (
            select(MarketOhlcvORM)
            .where(*filters)
            .order_by(MarketOhlcvORM.time)
            .limit(self._settings.FORECAST_PRICE_LOOKBACK_BARS)
        )
        rows = (await session.execute(stmt)).scalars().all()
        prices = [float(row.close) for row in rows if row.close is not None]
        volumes = [float(row.volume) for row in rows if row.volume is not None]
        return prices, volumes

    async def _load_liquidity_features(
        self,
        session: AsyncSession,
        instrument: InstrumentORM,
        *,
        as_of: datetime | None,
    ) -> tuple[float | None, float | None, float | None, float | None, float | None, float | None]:
        assessment = await self._liquidity_monitor.assess_instrument(
            session,
            instrument,
            as_of=as_of,
        )
        if assessment is None:
            return None, None, None, None, None, None

        prior_score = min(1.0, assessment.liquidity_score + 0.15)
        prior_depth = min(1.0, assessment.depth_ratio + 0.10)
        prior_spread = (
            assessment.spread_bps * 0.75
            if assessment.spread_bps is not None
            else None
        )
        return (
            assessment.spread_bps,
            assessment.depth_ratio,
            prior_spread,
            prior_depth,
            assessment.liquidity_score,
            prior_score,
        )

    async def _load_correlation_weights(
        self,
        session: AsyncSession,
        instrument_id: int,
    ) -> tuple[list[float], list[float]]:
        edges = await self._market_graph_repository.list_edges(
            session,
            edge_type=EdgeType.CORRELATION,
        )
        current = correlation_weights_for_instrument(edges, instrument_id)
        if not current:
            return [], []
        prior = [weight * 0.75 for weight in current]
        return current, prior

    async def _load_event_impact_score(
        self,
        session: AsyncSession,
        instrument: InstrumentORM,
        *,
        as_of: datetime | None,
    ) -> float:
        assessment = await self._event_risk_layer.assess_target(
            session,
            instrument.symbol,
            instrument_id=instrument.id,
            sector=(instrument.metadata_ or {}).get("sector"),
            as_of=as_of,
        )
        return compute_event_impact_score(
            news_impact_probability=assessment.news_impact_probability,
            news_shock_score=assessment.score,
        )


_engine = ForecastEngine()


def get_forecast_engine() -> ForecastEngine:
    return _engine
