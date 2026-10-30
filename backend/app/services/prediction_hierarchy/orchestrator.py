"""PredictionHierarchyOrchestrator — single entry point (Prompt 38)."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.market_data import MarketOhlcvORM, SectorMappingORM
from app.domain.regime import RegimeHistoryORM
from app.services.macro_registry.service import load_macro_snapshot
from app.services.control_fabric.risk_engine import RiskEngine, get_risk_engine
from app.services.control_fabric.risk_types import RiskBudgetContext, RiskEngineInput
from app.services.forecast.engine import ForecastEngine, get_forecast_engine
from app.services.forecast.types import ForecastInputBundle
from app.services.macro.sector_seed import sector_for_symbol
from app.services.market_graph.builder import build_correlation_edges, returns_from_closes
from app.services.market_graph.types import GraphEdgeRow
from app.services.prediction_hierarchy.action_forecast import (
    ActionForecastContext,
    ActionForecastEngine,
)
from app.services.prediction_hierarchy.cache import (
    FORECAST_CACHE_TTL_SECONDS,
    get_cached_forecast,
    set_cached_forecast,
)
from app.services.prediction_hierarchy.calibration_tracker import (
    GLOBAL_MACRO_SCOPE_ID,
    GLOBAL_MACRO_SCOPE_TYPE,
    resolve_live_calibration_error,
)
from app.services.prediction_hierarchy.confidence_calibrator import (
    CalibrationInput,
    ForecastConfidenceCalibrator,
)
from app.services.prediction_hierarchy.forecast_output import ForecastOutputBuilder, ForecastSourceBundle
from app.services.prediction_hierarchy.global_regime import (
    GlobalMacroRegimeEngine,
    MacroIndicatorSnapshot,
    compute_cross_asset_correlation,
)
from app.services.prediction_hierarchy.marginal_risk import (
    PortfolioMarginalRiskEngine,
    get_marginal_risk_engine,
)
from app.services.prediction_hierarchy.narrator import PredictionNarrator
from app.services.prediction_hierarchy.sector_regime import SectorRegimeEngine
from app.services.prediction_hierarchy.types import (
    ActionForecast,
    ActionRecommendation,
    DistributionForecast,
    ForecastOutput,
    GlobalRegimeResult,
    IntervalForecast,
    NarratorInsight,
    PointForecast,
    PointMagnitudeClass,
    PortfolioContext,
    ProposedPositionChange,
    RiskForecastLayer,
    ScenarioForecast,
    ScenarioForecastItem,
)
from app.services.regime.engine import RegimeEngine
from app.services.regime.features import prices_to_returns
from app.services.regime.types import InstrumentSeries
from app.services.scenario.engine import ScenarioEngine
from app.services.scenario.types import PortfolioPosition, PortfolioSnapshot


class PredictionHierarchyOrchestrator:
    """Official forecast path — external code must use this, not individual engines."""

    def __init__(
        self,
        *,
        global_engine: GlobalMacroRegimeEngine | None = None,
        sector_engine: SectorRegimeEngine | None = None,
        regime_engine: RegimeEngine | None = None,
        forecast_engine: ForecastEngine | None = None,
        marginal_engine: PortfolioMarginalRiskEngine | None = None,
        output_builder: ForecastOutputBuilder | None = None,
        action_engine: ActionForecastEngine | None = None,
        calibrator: ForecastConfidenceCalibrator | None = None,
        narrator: PredictionNarrator | None = None,
        risk_engine: RiskEngine | None = None,
        scenario_engine: ScenarioEngine | None = None,
        cache_ttl: int = FORECAST_CACHE_TTL_SECONDS,
    ) -> None:
        self._regime_engine = regime_engine or RegimeEngine()
        self._global_engine = global_engine or GlobalMacroRegimeEngine()
        self._sector_engine = sector_engine or SectorRegimeEngine(regime_engine=self._regime_engine)
        self._forecast_engine = forecast_engine or get_forecast_engine()
        self._marginal_engine = marginal_engine or get_marginal_risk_engine()
        self._output_builder = output_builder or ForecastOutputBuilder()
        self._action_engine = action_engine or ActionForecastEngine()
        self._calibrator = calibrator or ForecastConfidenceCalibrator()
        self._narrator = narrator or PredictionNarrator()
        self._risk_engine = risk_engine or get_risk_engine()
        self._scenario_engine = scenario_engine or ScenarioEngine()
        self._cache_ttl = cache_ttl

    async def get_forecast(
        self,
        db: AsyncSession,
        instrument_id: int,
        *,
        symbol: str,
        portfolio_context: PortfolioContext | None = None,
        include_narrative: bool = True,
        use_cache: bool = True,
        risk_budget: RiskBudgetContext | None = None,
        as_of: datetime | None = None,
    ) -> ForecastOutput:
        """Sequential hierarchy pipeline → ForecastOutput."""
        portfolio_hash = self._portfolio_hash(portfolio_context)
        if use_cache and as_of is None:
            cached = await get_cached_forecast(instrument_id, portfolio_hash)
            if cached and cached.get("symbol") == symbol.upper():
                return self._output_from_cache(cached)

        prices, volumes, spread_bps = await self._load_market_series(
            db,
            instrument_id,
            symbol=symbol,
            as_of=as_of,
        )
        if len(prices) < 10:
            return await self._build_degraded_forecast(
                db,
                instrument_id=instrument_id,
                symbol=symbol,
                include_narrative=include_narrative,
                portfolio_context=portfolio_context,
                portfolio_hash=portfolio_hash,
                use_cache=use_cache,
            )
        sector = (sector_for_symbol(symbol) or ("unknown", "unknown"))[0]
        as_of_ts = as_of if as_of is not None else datetime.now(timezone.utc)
        as_of_str = as_of_ts.isoformat()

        macro = await self._load_macro_indicators(db)
        asset_returns = await self._load_cross_asset_returns(db, instrument_id)
        global_result = await self._classify_global_with_history(db, macro, asset_returns)

        sector_instruments = await self._load_sector_instruments(db, sector)
        market_prices = self._sector_engine.aggregate_market_prices({sector: sector_instruments})
        sector_context = self._sector_engine.classify_sector_regime(
            sector,
            sector_instruments or {instrument_id: InstrumentSeries(prices=prices, volumes=volumes)},
            market_prices=market_prices or prices,
        )

        regime_result = self._regime_engine.classify_instrument(
            prices, volumes, spread_bps=spread_bps
        )
        forecast_bundle = await self._build_forecast_input_bundle(
            db,
            instrument_id=instrument_id,
            prices=prices,
            volumes=volumes,
            spread_bps=spread_bps,
            regime_result=regime_result,
            symbol=symbol,
        )
        ticker_forecast = self._forecast_engine.compute_from_inputs(forecast_bundle)

        returns = prices_to_returns(prices)
        marginal_impact = None
        risk_assessment = None
        correlation_edges: tuple[GraphEdgeRow, ...] = ()

        if portfolio_context and portfolio_context.positions:
            returns_by_instrument = dict(portfolio_context.returns_by_instrument)
            returns_by_instrument.setdefault(instrument_id, returns)
            correlation_edges = tuple(portfolio_context.correlation_edges) or tuple(
                build_correlation_edges(returns_by_instrument)
            )
            portfolio = PortfolioSnapshot(
                positions=tuple(portfolio_context.positions),
                factor_exposures=portfolio_context.factor_exposures or {},
                returns_by_instrument=returns_by_instrument,
                sector_by_instrument=portfolio_context.sector_by_instrument,
            )
            risk_inputs = RiskEngineInput(
                instrument_id=instrument_id,
                returns_by_instrument=returns_by_instrument,
                positions=tuple(portfolio_context.positions),
                correlation_edges=correlation_edges,
                sector_by_instrument=portfolio_context.sector_by_instrument or {},
                prices_by_instrument={instrument_id: prices},
                tail_risk_score=ticker_forecast.signals.tail_risk_score,
                liquidity_risk_score=ticker_forecast.signals.liquidity_deterioration_score,
            )
            budget = risk_budget or RiskBudgetContext(
                diversification_policy={},
                max_drawdown_pct=15.0,
                sleeve_risk_budget=Decimal(str(portfolio_context.remaining_risk_budget_var or 0)),
                profile_max_daily_loss=Decimal("0"),
            )
            risk_assessment = self._risk_engine.assess(risk_inputs, budget)
            what_if = self._marginal_engine.what_if(
                portfolio,
                ProposedPositionChange(instrument_id=instrument_id, delta_weight=0.05),
                correlation_edges=correlation_edges,
            )
            marginal_impact = self._marginal_engine.to_marginal_impact(what_if)

        scenario_portfolio = PortfolioSnapshot(
            positions=(PortfolioPosition(instrument_id=instrument_id, sleeve_id="default", weight=1.0),),
            factor_exposures={},
            returns_by_instrument={instrument_id: returns},
        )
        scenario_results = self._output_builder.run_default_scenarios(scenario_portfolio)
        scenario_dispersion = max(
            (abs(result.estimated_pnl_impact) for result in scenario_results),
            default=0.0,
        )

        live_calibration_error = await resolve_live_calibration_error(db, instrument_id=instrument_id)
        calibration = self._calibrator.calibrate(
            CalibrationInput(
                ticker_forecast=ticker_forecast,
                global_regime=global_result,
                sector_regime=sector_context,
                scenario_dispersion=scenario_dispersion,
                calibration_error=live_calibration_error,
            )
        )

        partial_bundle = ForecastSourceBundle(
            instrument_id=instrument_id,
            symbol=symbol.upper(),
            as_of=as_of_str,
            prices=prices,
            ticker_forecast=ticker_forecast,
            risk_assessment=risk_assessment,
            marginal_impact=marginal_impact,
            scenario_results=scenario_results,
            global_regime=global_result,
            sector_regime=sector_context,
            calibrated_confidence=calibration.calibrated_confidence,
            macro_indicators=macro,
        )

        action = self._action_engine.evaluate(
            ActionForecastContext(
                calibrated_confidence=calibration.calibrated_confidence,
                composite_risk_score=ticker_forecast.composite_risk_score,
                scenario_dispersion=scenario_dispersion,
                global_regime=global_result,
                sector_regime=sector_context,
                marginal_delta_var=marginal_impact.delta_var if marginal_impact else 0.0,
                remaining_risk_budget_var=(
                    portfolio_context.remaining_risk_budget_var if portfolio_context else None
                ),
                tail_risk_score=ticker_forecast.signals.tail_risk_score,
                volatility_expansion_probability=ticker_forecast.signals.volatility_expansion_probability,
            )
        )

        output = self._output_builder.build(
            replace(partial_bundle, action_forecast=action)
        )

        if include_narrative:
            cluster_pct = marginal_impact.new_correlation_cluster_exposure if marginal_impact else 0.0
            insights = self._narrator.narrate(
                output,
                news_impact_probability=ticker_forecast.signals.event_impact_score,
                correlation_cluster_pct=cluster_pct,
            )
            instruction = self._narrator.build_instruction_block(output, insights)
            basis = self._narrator.build_basis_block(output, ticker_forecast=ticker_forecast)
            output = ForecastOutput(
                instrument_id=output.instrument_id,
                symbol=output.symbol,
                as_of=output.as_of,
                point_forecast=output.point_forecast,
                interval_forecast=output.interval_forecast,
                distribution_forecast=output.distribution_forecast,
                scenario_forecast=output.scenario_forecast,
                risk_forecast=output.risk_forecast,
                action_forecast=output.action_forecast,
                calibrated_confidence=output.calibrated_confidence,
                high_confidence=output.high_confidence,
                global_regime=output.global_regime,
                sector_regime=output.sector_regime,
                narrator_insights=insights,
                raw_ticker_confidence=output.raw_ticker_confidence,
                instruction_block=instruction,
                basis_block=basis,
                risk_engine_report=output.risk_engine_report,
                prediction_system_report=output.prediction_system_report,
                metadata={
                    "calibration_components": calibration.components,
                    "global_cap_applied": calibration.global_cap_applied,
                    "calibration_error": calibration.calibration_error,
                },
            )

        if use_cache:
            await set_cached_forecast(
                instrument_id,
                output.to_dict(),
                portfolio_hash=portfolio_hash,
                ttl=self._cache_ttl,
            )
        return output

    @staticmethod
    def _portfolio_hash(portfolio: PortfolioContext | None) -> str:
        if portfolio is None or not portfolio.positions:
            return "none"
        raw = str(sorted((p.instrument_id, p.weight) for p in portfolio.positions))
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    @staticmethod
    async def _load_market_series(
        db: AsyncSession,
        instrument_id: int,
        *,
        symbol: str | None = None,
        as_of: datetime | None = None,
    ) -> tuple[list[float], list[float], float | None]:
        if not symbol:
            filters = [
                MarketOhlcvORM.instrument_id == instrument_id,
                MarketOhlcvORM.timeframe == "1d",
            ]
            if as_of is not None:
                cutoff = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
                filters.append(MarketOhlcvORM.time <= cutoff)
            stmt = (
                select(MarketOhlcvORM)
                .where(*filters)
                .order_by(MarketOhlcvORM.time.desc())
                .limit(120)
            )
            rows = list((await db.execute(stmt)).scalars().all())
            rows.reverse()
            prices = [float(row.close) for row in rows if row.close]
            volumes = [float(row.volume or 0) for row in rows]
            return prices, volumes, None

        from app.services.market_data.series_loader import load_forecast_price_series

        prices, volumes, _source = await load_forecast_price_series(
            db,
            instrument_id,
            symbol,
            limit=120,
            as_of=as_of,
        )
        return prices, volumes, None

    async def _build_forecast_input_bundle(
        self,
        db: AsyncSession,
        *,
        instrument_id: int,
        prices: list[float],
        volumes: list[float],
        spread_bps: float | None,
        regime_result: Any,
        symbol: str,
    ) -> ForecastInputBundle:
        """Load full signal inputs — same enrichment path as ForecastEngine.forecast_instrument()."""
        from app.domain.instrument import InstrumentORM
        from app.services.forecast.signals import correlation_weights_for_instrument
        from app.services.market_graph.repository import MarketGraphRepository
        from app.services.market_graph.types import EdgeType

        instrument = await db.get(InstrumentORM, instrument_id)
        correlation_weights: list[float] = []
        prior_correlation_weights: list[float] = []
        event_score = 0.0
        liquidity_score = None
        prior_liquidity_score = None
        depth_ratio = None
        prior_depth_ratio = None
        prior_spread_bps = None

        if instrument is not None:
            try:
                repo = MarketGraphRepository()
                edges = await repo.list_edges(db, edge_type=EdgeType.CORRELATION)
                correlation_weights = correlation_weights_for_instrument(edges, instrument_id)
                if correlation_weights:
                    prior_correlation_weights = [w * 0.75 for w in correlation_weights]
            except Exception:
                pass

            try:
                assessment = await self._forecast_engine._liquidity_monitor.assess_instrument(
                    db, instrument
                )
                if assessment is not None:
                    liquidity_score = assessment.liquidity_score
                    prior_liquidity_score = min(1.0, assessment.liquidity_score + 0.15)
                    depth_ratio = assessment.depth_ratio
                    prior_depth_ratio = min(1.0, assessment.depth_ratio + 0.10)
                    spread_bps = assessment.spread_bps if spread_bps is None else spread_bps
                    prior_spread_bps = (
                        assessment.spread_bps * 0.75 if assessment.spread_bps is not None else None
                    )
            except Exception:
                pass

            try:
                event_assessment = await self._forecast_engine._event_risk_layer.assess_target(
                    db,
                    instrument.symbol,
                    instrument_id=instrument.id,
                    sector=(instrument.metadata_ or {}).get("sector"),
                )
                from app.services.forecast.signals import compute_event_impact_score

                event_score = compute_event_impact_score(
                    news_impact_probability=event_assessment.news_impact_probability,
                    news_shock_score=event_assessment.score,
                )
            except Exception:
                pass

        return ForecastInputBundle(
            instrument_id=instrument_id,
            prices=prices,
            volumes=volumes,
            spread_bps=spread_bps,
            regime_result=regime_result,
            correlation_edge_weights=correlation_weights,
            prior_correlation_edge_weights=prior_correlation_weights,
            liquidity_score=liquidity_score,
            prior_liquidity_score=prior_liquidity_score,
            depth_ratio=depth_ratio,
            prior_depth_ratio=prior_depth_ratio,
            prior_spread_bps=prior_spread_bps,
            event_impact_score=event_score,
        )

    async def _build_degraded_forecast(
        self,
        db: AsyncSession,
        *,
        instrument_id: int,
        symbol: str,
        include_narrative: bool,
        portfolio_context: PortfolioContext | None,
        portfolio_hash: str,
        use_cache: bool,
    ) -> ForecastOutput:
        """Macro-only forecast when instrument bars are unavailable."""
        as_of = datetime.now(timezone.utc).isoformat()
        macro = await self._load_macro_indicators(db)
        global_result = await self._classify_global_with_history(db, macro, [])

        degraded_note = (
            f"По {symbol.upper()} пока недостаточно истории цен — "
            "ниже макро-контекст и осторожная оценка. Данные обновляются автоматически."
        )
        narrator_insights: tuple[NarratorInsight, ...] = ()
        if include_narrative:
            narrator_insights = (
                NarratorInsight(
                    template_id="degraded_instrument_data",
                    text_ru=degraded_note,
                    text_en=(
                        f"Insufficient price history for {symbol.upper()} — "
                        "showing macro context only."
                    ),
                    source_metric="bars_available",
                    source_value=0.0,
                ),
            )
            if global_result.dominant_regime:
                narrator_insights = narrator_insights + (
                    NarratorInsight(
                        template_id="degraded_macro_regime",
                        text_ru=(
                            f"Макро-режим: {global_result.dominant_regime.replace('_', ' ')} "
                            f"(уверенность {global_result.confidence:.0%})."
                        ),
                        text_en=f"Macro regime: {global_result.dominant_regime}.",
                        source_metric="global_regime.confidence",
                        source_value=global_result.confidence,
                    ),
                )

        output = ForecastOutput(
            instrument_id=instrument_id,
            symbol=symbol.upper(),
            as_of=as_of,
            point_forecast=PointForecast(
                magnitude_class=PointMagnitudeClass.NEUTRAL,
                expected_return_sign=0,
                momentum_score=0.5,
                plain_language_summary=degraded_note,
            ),
            interval_forecast=IntervalForecast(
                horizon_days=10,
                p10=-0.05,
                p90=0.05,
                rolling_volatility=0.0,
                confidence_multiplier=1.645,
                plain_language_summary="Интервал оценён по макро-волатильности — точность ограничена.",
            ),
            distribution_forecast=DistributionForecast(
                p5=0.0,
                p25=0.0,
                p50=0.0,
                p75=0.0,
                p95=0.0,
                method="degraded_macro_only",
                plain_language_summary=degraded_note,
            ),
            scenario_forecast=ScenarioForecast(
                scenarios=(
                    ScenarioForecastItem(
                        name="macro_uncertainty",
                        probability=round(global_result.confidence, 4),
                        impact=0.0,
                        label_ru="Макро-неопределённость",
                        scenario_type="degraded",
                        impact_narrative_ru=degraded_note,
                    ),
                ),
                scenario_dispersion=0.0,
            ),
            risk_forecast=RiskForecastLayer(
                instrument_metrics={"composite_risk_score": 0.5},
                portfolio_metrics={},
                plain_language_summary="Риск по инструменту оценён консервативно из-за неполных данных.",
            ),
            action_forecast=ActionForecast(
                recommendation=ActionRecommendation.WAIT,
                reason=degraded_note,
                rule_id="degraded_insufficient_bars",
            ),
            calibrated_confidence=round(global_result.confidence * 0.45, 4),
            high_confidence=False,
            global_regime=global_result,
            narrator_insights=narrator_insights,
            metadata={
                "degraded": True,
                "degraded_reason": "instrument_bars_missing",
                "macro_indicators": macro,
            },
        )

        if use_cache:
            await set_cached_forecast(
                instrument_id,
                output.to_dict(),
                portfolio_hash=portfolio_hash,
                ttl=self._cache_ttl,
            )
        return output

    @staticmethod
    async def _load_macro_indicators(db: AsyncSession) -> dict[str, float]:
        return await load_macro_snapshot(db)

    @staticmethod
    def _macro_indicator_snapshot(
        macro: dict[str, float],
        asset_returns: list[list[float]],
    ) -> MacroIndicatorSnapshot:
        """Build macro snapshot — prefer FRED HY OAS + 10Y over precomputed spread alone."""
        hy_oas = macro.get("hy_oas")
        gov_10y = macro.get("gov_10y")
        credit_spread = macro.get("credit_spread")
        if hy_oas is not None and gov_10y is not None:
            credit_spread = None
        return MacroIndicatorSnapshot(
            rate_cb=macro.get("rate_cb"),
            cpi=macro.get("cpi"),
            unemployment=macro.get("unemployment"),
            dxy=macro.get("dxy"),
            vix=macro.get("vix"),
            oil_brent=macro.get("oil_brent"),
            cross_asset_correlation=compute_cross_asset_correlation(asset_returns),
            credit_spread_proxy=credit_spread,
            hy_oas_pct=hy_oas,
            gov_10y_pct=gov_10y,
        )

    async def classify_global_macro(
        self,
        db: AsyncSession,
        macro: dict[str, float],
        *,
        asset_returns: list[list[float]] | None = None,
    ) -> GlobalRegimeResult:
        """Shared global-regime path with history persistence (orchestrator boundary)."""
        return await self._classify_global_with_history(db, macro, asset_returns or [])

    async def _classify_global_with_history(
        self,
        db: AsyncSession,
        macro: dict[str, float],
        asset_returns: list[list[float]],
    ) -> GlobalRegimeResult:
        await self._bootstrap_global_engine_history(db)
        snapshot = self._macro_indicator_snapshot(macro, asset_returns)
        global_result = self._global_engine.classify(
            snapshot,
            previous_regime=self._global_engine._previous_regime,
            regime_age_bars=self._global_engine._regime_age_bars,
        )
        prev_dominant, age_bars = self._global_engine.update_regime_history(
            global_result.dominant_regime
        )
        observed_at = datetime.now(timezone.utc)
        if prev_dominant != global_result.dominant_regime:
            await self._persist_global_regime_transition(
                db,
                global_result,
                previous_regime=prev_dominant,
                regime_age_bars=age_bars,
                observed_at=observed_at,
            )
        else:
            await self._touch_global_regime_age(
                db,
                global_result.dominant_regime,
                regime_age_bars=age_bars,
                observed_at=observed_at,
            )
        return global_result

    async def _bootstrap_global_engine_history(self, db: AsyncSession) -> None:
        if self._global_engine._previous_regime is not None:
            return
        dominant, age = await self._load_latest_global_regime_state(db)
        if dominant is None:
            return
        self._global_engine._previous_regime = dominant
        self._global_engine._regime_age_bars = age

    @staticmethod
    async def _load_latest_global_regime_state(db: AsyncSession) -> tuple[str | None, int]:
        stmt = (
            select(RegimeHistoryORM)
            .where(
                RegimeHistoryORM.scope_type == GLOBAL_MACRO_SCOPE_TYPE,
                RegimeHistoryORM.scope_id == GLOBAL_MACRO_SCOPE_ID,
            )
            .order_by(RegimeHistoryORM.time.desc())
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None, 0
        features = row.features if isinstance(row.features, dict) else {}
        age = int(features.get("regime_age_bars", 1))
        return row.dominant_regime, age

    @staticmethod
    async def _persist_global_regime_transition(
        db: AsyncSession,
        global_result: GlobalRegimeResult,
        *,
        previous_regime: str | None,
        regime_age_bars: int,
        observed_at: datetime,
    ) -> None:
        row = RegimeHistoryORM(
            time=observed_at,
            scope_type=GLOBAL_MACRO_SCOPE_TYPE,
            scope_id=GLOBAL_MACRO_SCOPE_ID,
            regime_distribution=dict(global_result.distribution),
            dominant_regime=global_result.dominant_regime,
            confidence=global_result.confidence,
            previous_regime=previous_regime,
            features={
                "credit_spread_proxy": global_result.credit_spread_proxy,
                "credit_spread_source": global_result.credit_spread_source,
                "confidence_damping_active": global_result.confidence_damping_active,
                "regime_age_bars": regime_age_bars,
            },
        )
        db.add(row)
        await db.flush()

    @staticmethod
    async def _touch_global_regime_age(
        db: AsyncSession,
        dominant_regime: str,
        *,
        regime_age_bars: int,
        observed_at: datetime,
    ) -> None:
        stmt = (
            select(RegimeHistoryORM)
            .where(
                RegimeHistoryORM.scope_type == GLOBAL_MACRO_SCOPE_TYPE,
                RegimeHistoryORM.scope_id == GLOBAL_MACRO_SCOPE_ID,
                RegimeHistoryORM.dominant_regime == dominant_regime,
            )
            .order_by(RegimeHistoryORM.time.desc())
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return
        features = dict(row.features or {})
        features["regime_age_bars"] = regime_age_bars
        features["last_seen_at"] = observed_at.isoformat()
        row.features = features
        row.time = observed_at
        await db.flush()

    @staticmethod
    async def _load_cross_asset_returns(
        db: AsyncSession,
        instrument_id: int,
    ) -> list[list[float]]:
        stmt = (
            select(MarketOhlcvORM)
            .where(MarketOhlcvORM.timeframe == "1d")
            .order_by(MarketOhlcvORM.time.desc())
            .limit(500)
        )
        rows = list((await db.execute(stmt)).scalars().all())
        by_instrument: dict[int, list[float]] = {}
        for row in rows:
            if row.close is None:
                continue
            by_instrument.setdefault(row.instrument_id, []).append(float(row.close))
        for prices in by_instrument.values():
            prices.reverse()
        result: list[list[float]] = []
        target = by_instrument.get(instrument_id, [])
        if target:
            series = returns_from_closes(target)
            if len(series) >= 5:
                result.append(series)
        for iid, prices in by_instrument.items():
            if iid == instrument_id:
                continue
            series = returns_from_closes(prices)
            if len(series) >= 5:
                result.append(series)
            if len(result) >= 4:
                break
        return result

    async def _load_sector_instruments(
        self,
        db: AsyncSession,
        sector: str,
    ) -> dict[int, InstrumentSeries]:
        stmt = select(SectorMappingORM).where(SectorMappingORM.sector == sector)
        mappings = list((await db.execute(stmt)).scalars().all())
        instruments: dict[int, InstrumentSeries] = {}
        for mapping in mappings:
            prices, volumes, spread = await self._load_market_series(db, mapping.instrument_id)
            if prices:
                instruments[mapping.instrument_id] = InstrumentSeries(
                    prices=prices,
                    volumes=volumes,
                    spread_bps=spread,
                )
        return instruments

    @staticmethod
    def _output_from_cache(cached: dict[str, Any]) -> ForecastOutput:
        from app.services.prediction_hierarchy.types import ActionRecommendation, GlobalRegimeResult, SectorRegimeContext, SectorRotationScore, SectorRotationFlag

        point_raw = cached.get("point_forecast", {})
        interval_raw = cached.get("interval_forecast", {})
        dist_raw = cached.get("distribution_forecast", {})
        scenario_raw = cached.get("scenario_forecast", {})
        scenarios = tuple(
            ScenarioForecastItem(
                name=str(item.get("name", "scenario")),
                probability=float(item.get("probability", 0.0)),
                impact=float(item.get("impact", 0.0)),
                label_ru=str(item.get("label_ru", "")),
                scenario_type=str(item.get("scenario_type", "")),
                impact_narrative_ru=str(item.get("impact_narrative_ru", "")),
            )
            for item in scenario_raw.get("scenarios", [])
            if isinstance(item, dict)
        )
        risk_raw = cached.get("risk_forecast", {})
        action_raw = cached.get("action_forecast", {})

        global_regime = None
        global_raw = cached.get("global_regime")
        if isinstance(global_raw, dict):
            global_regime = GlobalRegimeResult(
                distribution=global_raw.get("distribution", {}),
                dominant_regime=str(global_raw.get("dominant_regime", "macro_uncertainty")),
                confidence=float(global_raw.get("confidence", 0.5)),
                confirmation_window_bars=5,
                confidence_damping_active=False,
                credit_spread_proxy=global_raw.get("credit_spread_proxy"),
                credit_spread_source=str(global_raw.get("credit_spread_source") or "unavailable"),
            )

        sector_regime = None
        sector_raw = cached.get("sector_regime")
        if isinstance(sector_raw, dict):
            regime_raw = sector_raw.get("regime", {})
            rotation_raw = sector_raw.get("rotation", {})
            from app.services.regime.types import RegimeClassificationResult

            regime = RegimeClassificationResult(
                distribution=regime_raw.get("distribution", {}),
                dominant_regime=str(regime_raw.get("dominant_regime", "choppy_range")),
                confidence=0.5,
                feature_sequence=(),
            )
            rotation = SectorRotationScore(
                sector=str(sector_raw.get("sector", "unknown")),
                score_1w=0.0,
                score_1m=0.0,
                score_3m=0.0,
                composite_score=float(rotation_raw.get("composite_score", 0.0)),
                rotation_flag=SectorRotationFlag(
                    rotation_raw.get("rotation_flag", SectorRotationFlag.NEUTRAL.value)
                ),
            )
            sector_regime = SectorRegimeContext(
                sector=str(sector_raw.get("sector", "unknown")),
                regime=regime,
                rotation=rotation,
                sector_momentum=0.0,
            )

        narrator_raw = cached.get("narrator_insights", [])
        from app.services.prediction_hierarchy.types import NarratorInsight

        narrator_insights = tuple(
            NarratorInsight(
                template_id="cached",
                text_ru=str(item.get("text_ru", "")),
                text_en=str(item.get("text_en", "")),
                source_metric="cache",
                source_value=0.0,
            )
            for item in narrator_raw
            if isinstance(item, dict)
        )

        return ForecastOutput(
            instrument_id=int(cached["instrument_id"]),
            symbol=str(cached["symbol"]),
            as_of=str(cached["as_of"]),
            point_forecast=PointForecast(
                magnitude_class=PointMagnitudeClass(point_raw.get("magnitude_class", "neutral")),
                expected_return_sign=int(point_raw.get("expected_return_sign", 0)),
                momentum_score=float(point_raw.get("momentum_score", 0.0)),
            ),
            interval_forecast=IntervalForecast(
                horizon_days=int(interval_raw.get("horizon_days", 10)),
                p10=float(interval_raw.get("p10", 0.0)),
                p90=float(interval_raw.get("p90", 0.0)),
                rolling_volatility=float(interval_raw.get("rolling_volatility", 0.0)),
                confidence_multiplier=float(interval_raw.get("confidence_multiplier", 1.645)),
                plain_language_summary=str(interval_raw.get("plain_language_summary", "")),
            ),
            distribution_forecast=DistributionForecast(
                p5=float(dist_raw.get("p5", 0.0)),
                p25=float(dist_raw.get("p25", 0.0)),
                p50=float(dist_raw.get("p50", 0.0)),
                p75=float(dist_raw.get("p75", 0.0)),
                p95=float(dist_raw.get("p95", 0.0)),
                method="cached",
            ),
            scenario_forecast=ScenarioForecast(
                scenarios=scenarios,
                scenario_dispersion=float(scenario_raw.get("scenario_dispersion", 0.0)),
                overlay_breakdown=scenario_raw.get("overlay_breakdown") or {},
                overlay_audit=scenario_raw.get("overlay_audit") or {},
            ),
            risk_forecast=RiskForecastLayer(
                instrument_metrics=risk_raw.get("instrument_metrics", {}),
                portfolio_metrics=risk_raw.get("portfolio_metrics", {}),
            ),
            action_forecast=ActionForecast(
                recommendation=ActionRecommendation(action_raw.get("recommendation", "wait")),
                reason=str(action_raw.get("reason", "")),
                rule_id="cached",
            ),
            calibrated_confidence=float(cached.get("calibrated_confidence", 0.0)),
            high_confidence=bool(cached.get("high_confidence", False)),
            global_regime=global_regime,
            sector_regime=sector_regime,
            narrator_insights=narrator_insights,
        )


_orchestrator = PredictionHierarchyOrchestrator()


def get_hierarchy_orchestrator() -> PredictionHierarchyOrchestrator:
    return _orchestrator
