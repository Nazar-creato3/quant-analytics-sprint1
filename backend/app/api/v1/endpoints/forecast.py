"""Read-only Forecasting API — regime, factors, probability map, risk metrics."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db
from app.core.logging import get_logger
from app.schemas.forecast import (
    BullBaseBearOut,
    ConformalIntervalOut,
    DailyForecastItem,
    DailyForecastOut,
    EnsembleForecastOut,
    EnsembleModelOut,
    ForecastHealthOut,
    ForecastNarrativeOut,
    ForecastOut,
    GlobalMacroViewOut,
    LiveDirectionAccuracyOut,
    MarketForecastOut,
    MarketPredictionSummaryOut,
    ScenarioDisclosureOut,
    StructuredForecastSections,
    TrackRecordChartOut,
)
from app.services.analysis.context import gather_analysis_context
from app.services.analysis.enrichment import enrich_structured_forecast
from app.services.explainability.layer import ExplainabilityLayer
from app.services.forecast.daily_builder import get_daily_forecast_builder
from app.services.forecast.market_forecast import build_market_forecast
from app.services.forecast.scenario_disclosure_narrator import ScenarioDisclosureNarrator
from app.services.forecast.snapshot_repository import latest_snapshots_for_symbols
from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator
from app.services.forecast.outlook_normalize import normalize_market_outlook_item
from app.services.forecast.probability_map import (
    build_hierarchy_probability_map,
    build_metric_validity,
    build_probability_map_data_quality,
    resolve_factor_exposures_for_forecast,
)
from app.services.settings.watchlist import get_effective_watchlist

logger = get_logger(__name__)
router = APIRouter(prefix="/forecast", tags=["forecasting"])

_FORECAST_USER_MESSAGE = (
    "Прогноз временно недоступен — обновляем рыночные данные. "
    "Повторите запрос через минуту."
)
# LLM narrative budget — must exceed internal verdict LLM cap (45s) but still bounded.
_FORECAST_LLM_NARRATIVE_TIMEOUT_SEC = 55.0
# Optional upgrade layers (global macro multi-symbol fetch) must not block core JSON.
_FORECAST_UPGRADE_LAYERS_TIMEOUT_SEC = 20.0


def _friendly_forecast_detail(exc: Exception, symbol: str) -> str:
    from app.services.llm.errors import AITunnelUnavailableError

    from app.services.llm.errors import LLM_UNAVAILABLE_USER_RU

    if isinstance(exc, AITunnelUnavailableError):
        # str(exc) carries the technical reason (HTTP code, balance); the log has it, the user does not need it.
        return LLM_UNAVAILABLE_USER_RU
    if isinstance(exc, TypeError):
        logger.warning("Forecast TypeError surfaced to client", symbol=symbol, error=str(exc))
        return LLM_UNAVAILABLE_USER_RU
    msg = str(exc).lower()
    if "insufficient" in msg or "market data" in msg:
        return (
            f"По {symbol.upper()} пока формируется история цен. "
            "Макро-прогноз доступен на вкладке «Рынок» — повторите через минуту."
        )
    return _FORECAST_USER_MESSAGE


async def _resolve_instrument(db: AsyncSession, symbol: str):
    from app.services.instrument.resolver import resolve_or_create_instrument

    try:
        return await resolve_or_create_instrument(db, symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Instrument resolution failed", symbol=symbol, error=str(exc))
        raise HTTPException(status_code=503, detail=f"Instrument resolution failed: {exc}") from exc


def _normalize_prediction_item(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    item = dict(raw)
    label = (
        item.get("label")
        or item.get("scenario")
        or item.get("regime")
        or item.get("name")
        or item.get("engine")
    )
    if not label:
        return None
    item["label"] = str(label)
    item.setdefault("label_ru", str(item.get("label_ru") or label))
    item.setdefault("probability", float(item.get("probability", 0.5) or 0.5))
    item.setdefault("engine", str(item.get("engine") or "ForecastEngine"))
    return item


def _normalize_prediction_list(items: object) -> list[dict]:
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for raw in items:
        norm = _normalize_prediction_item(raw)
        if norm is not None:
            out.append(norm)
    return out


def _structured_from_payload(payload: dict) -> StructuredForecastSections:
    default_prob = float(payload.get("confidence", 0.5) or 0.5)
    market_outlook = [
        normalize_market_outlook_item(item, default_probability=default_prob)
        for item in payload.get("market_outlook", [])
    ]
    return StructuredForecastSections(
        market_outlook=market_outlook,
        sector_opportunities=_normalize_prediction_list(payload.get("sector_opportunities")),
        sector_risks=_normalize_prediction_list(payload.get("sector_risks")),
        regime_forecast=payload.get("regime_forecast", {}),
        tail_risk_events=_normalize_prediction_list(payload.get("tail_risk_events")),
        actionable_summary=payload.get("actionable_summary", []),
        high_confidence_predictions=_normalize_prediction_list(
            payload.get("high_confidence_predictions")
        ),
        engines_used=payload.get("engines_used", []),
    )


def _parse_as_of(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class _AiNotRequested(Exception):
    """Paid model text is generated only when a person asks for it."""


def _ai_allowed(explain: bool) -> bool:
    from app.core.config import settings as _s

    return bool(explain or getattr(_s, "LLM_AUTO_EXPLAIN", False))


async def _apply_forecast_llm_narrative(
    db: AsyncSession,
    *,
    symbol: str,
    hierarchy,
    disclosure_dict: dict,
    structured: StructuredForecastSections,
    track_record_out: TrackRecordChartOut | None,
    live_direction_accuracy_out: LiveDirectionAccuracyOut | None,
) -> tuple[str | None, dict, StructuredForecastSections]:
    """Run scenario verdict LLM (with in-memory tool payload) and optional fallback narrative."""
    from app.services.forecast.forecast_narrative_llm import (
        apply_llm_narrative_to_disclosure,
        try_llm_forecast_narrative,
    )
    from app.services.forecast.scenario_verdict_llm import (
        tool_payload_from_hierarchy,
        try_generate_scenario_verdict,
    )

    drift_flag = bool(track_record_out.drift_flag) if track_record_out else False
    cal_error = (
        track_record_out.aggregate_calibration_error if track_record_out else None
    )
    tool_payload = tool_payload_from_hierarchy(
        hierarchy,
        disclosure_dict,
        live_direction_accuracy=live_direction_accuracy_out,
        track_record=track_record_out,
    )

    llm_narrative: str | None = None
    verdict_layers = await try_generate_scenario_verdict(
        db,
        symbol=symbol,
        hierarchy=hierarchy,
        disclosure=disclosure_dict,
        drift_flag=drift_flag,
        aggregate_calibration_error=cal_error,
        rolling_regime_accuracy=(
            track_record_out.rolling_accuracy if track_record_out else None
        ),
        tool_payload=tool_payload,
    )
    if verdict_layers:
        disclosure_dict = apply_llm_narrative_to_disclosure(
            disclosure_dict,
            "\n".join(verdict_layers),
        )
        llm_narrative = "\n".join(verdict_layers)

    if not llm_narrative:
        llm_narrative = await try_llm_forecast_narrative(
            symbol=symbol,
            hierarchy=hierarchy,
            disclosure=disclosure_dict,
        )
        if llm_narrative:
            disclosure_dict = apply_llm_narrative_to_disclosure(disclosure_dict, llm_narrative)

    if llm_narrative:
        engines = list(structured.engines_used or [])
        if "LLMForecastNarrative" not in engines:
            engines.append("LLMForecastNarrative")
        structured = StructuredForecastSections(
            **{
                **structured.model_dump(),
                "engines_used": engines,
                "actionable_summary": [llm_narrative.strip()]
                + list(structured.actionable_summary or []),
            }
        )
    return llm_narrative, disclosure_dict, structured


async def _build_forecast_response(
    db: AsyncSession,
    instrument,
    *,
    use_snapshot: bool = False,
    include_narrative: bool = True,
    include_llm: bool = False,
) -> ForecastOut:
    orchestrator = get_hierarchy_orchestrator()
    builder = get_daily_forecast_builder()

    snapshot_id = None
    as_of = None
    structured: StructuredForecastSections | None = None
    payload: dict | None = None

    if use_snapshot:
        from app.services.forecast.snapshot_repository import latest_snapshot_for_symbol

        snap = await latest_snapshot_for_symbol(db, instrument.symbol)
        if snap is not None:
            payload = snap.payload or {}
            snapshot_id = snap.id
            as_of = snap.snapshot_date
            structured = _structured_from_payload(payload)

    try:
        hierarchy = await orchestrator.get_forecast(
            db,
            instrument.id,
            symbol=instrument.symbol,
            include_narrative=include_narrative,
            use_cache=True,
        )
    except ValueError as exc:
        logger.warning("Hierarchy forecast failed", symbol=instrument.symbol, error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=_friendly_forecast_detail(exc, instrument.symbol),
        ) from exc
    except Exception as exc:
        logger.warning("Hierarchy forecast failed", symbol=instrument.symbol, error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=_friendly_forecast_detail(exc, instrument.symbol),
        ) from exc

    if payload is None:
        try:
            payload = await builder.build(db, instrument_id=instrument.id, symbol=instrument.symbol)
            structured = _structured_from_payload(payload)
            as_of = _parse_as_of(payload.get("as_of"))
        except Exception as exc:
            logger.warning("Structured forecast build failed", symbol=instrument.symbol, error=str(exc))

    snapshot = None
    try:
        explain = ExplainabilityLayer()
        snapshot = await explain.explain_for_instrument(db, instrument.id)
    except Exception as exc:
        logger.warning("Explainability failed", symbol=instrument.symbol, error=str(exc))

    payload_factors = payload.get("factor_exposures", {}) if payload else {}
    risk_metrics: dict = {}
    if snapshot and snapshot.source_metrics.get("risk"):
        risk_metrics = {
            k: v for k, v in snapshot.source_metrics.get("risk", {}).items() if v is not None
        }
    hierarchy_risk = {
        k: float(v)
        for k, v in hierarchy.risk_forecast.instrument_metrics.items()
        if isinstance(v, (int, float))
    }
    risk_metrics.update(hierarchy_risk)

    narrator_texts = [insight.text_ru for insight in hierarchy.narrator_insights]

    macro: dict = {}
    macro_bundle: dict = {}
    try:
        from app.services.macro_registry.service import load_macro_snapshot_bundle

        macro_bundle = await load_macro_snapshot_bundle(db)
        macro = macro_bundle.get("indicators") or {}
    except Exception:
        macro = {}
        macro_bundle = {}

    disclosure = ScenarioDisclosureNarrator().from_hierarchy_dict(
        hierarchy.to_dict(),
        macro=macro,
        macro_bundle=macro_bundle,
        global_result=hierarchy.global_regime,
        rotation_scores=(
            (hierarchy.sector_regime.rotation,) if hierarchy.sector_regime else ()
        ),
        symbol=instrument.symbol,
        scope="symbol",
    )

    analysis_ctx = await gather_analysis_context(
        db,
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        output=hierarchy,
        include_structured=False,
    )
    ta_factors = analysis_ctx.ticker_analysis.factor_exposures if analysis_ctx.ticker_analysis else None
    factor_exposures = resolve_factor_exposures_for_forecast(
        payload_factors=payload_factors,
        analysis_factors=analysis_ctx.factor_exposures,
        ticker_analysis_factors=ta_factors,
    )
    if analysis_ctx.ticker_analysis and analysis_ctx.ticker_analysis.risk_metrics:
        for key, val in analysis_ctx.ticker_analysis.risk_metrics.items():
            if val is not None and key not in hierarchy_risk:
                risk_metrics[key] = val

    probability_map = build_hierarchy_probability_map(hierarchy)
    metric_validity = build_metric_validity(hierarchy)
    data_quality = build_probability_map_data_quality(hierarchy)

    structured = enrich_structured_forecast(
        structured,
        hierarchy=hierarchy,
        payload=payload,
        analysis=analysis_ctx,
        narrator_texts=narrator_texts,
        disclosure=disclosure,
        symbol=instrument.symbol,
    )
    default_prob = hierarchy.calibrated_confidence
    structured = StructuredForecastSections(
        market_outlook=[
            normalize_market_outlook_item(item, default_probability=default_prob)
            for item in (structured.market_outlook or [])
        ],
        sector_opportunities=list(structured.sector_opportunities or []),
        sector_risks=list(structured.sector_risks or []),
        regime_forecast=structured.regime_forecast or {},
        tail_risk_events=list(structured.tail_risk_events or []),
        actionable_summary=list(structured.actionable_summary or []),
        high_confidence_predictions=list(structured.high_confidence_predictions or []),
        engines_used=list(structured.engines_used or []),
    )

    disclosure_dict = disclosure.to_dict()
    llm_narrative = None

    # UI defers LLM to /narrative — avoid flashing template paragraphs.
    if include_narrative and not include_llm:
        disclosure_dict = {**disclosure_dict, "paragraphs": [], "engines_used": []}

    if not include_narrative:
        action_rec = None
        if hierarchy.action_forecast and hierarchy.action_forecast.recommendation:
            action_rec = hierarchy.action_forecast.recommendation.value
        try:
            hierarchy_dict = hierarchy.to_dict()
        except Exception as exc:
            logger.warning("Hierarchy to_dict failed", symbol=instrument.symbol, error=str(exc))
            hierarchy_dict = {
                "symbol": instrument.symbol,
                "instrument_id": instrument.id,
                "calibrated_confidence": hierarchy.calibrated_confidence,
            }
        core_beat = None
        try:
            from app.services.forecast.market_beat import market_beat_from_db

            core_beat = await market_beat_from_db(db, instrument.symbol)
        except Exception as exc:
            logger.debug("core market_beat skipped", symbol=instrument.symbol, error=str(exc))
        return ForecastOut(
            symbol=instrument.symbol,
            instrument_id=instrument.id,
            dominant_regime=hierarchy.global_regime.dominant_regime if hierarchy.global_regime else None,
            regime_distribution=(
                hierarchy.sector_regime.regime.distribution if hierarchy.sector_regime else {}
            ),
            composite_risk_score=hierarchy.risk_forecast.instrument_metrics.get(
                "composite_risk_score", 0.0
            ),
            confidence=hierarchy.calibrated_confidence,
            risk_flags=list(hierarchy.risk_forecast.breached_metrics),
            factor_exposures=factor_exposures,
            probability_map=probability_map,
            metric_validity=metric_validity,
            data_quality=data_quality,
            forecast_explanation=snapshot.forecast_explanation if snapshot else None,
            regime_explanation=snapshot.regime_explanation if snapshot else None,
            risk_explanation=snapshot.risk_explanation if snapshot else None,
            risk_engine_metrics=risk_metrics,
            source_metrics=snapshot.source_metrics if snapshot else {},
            structured=structured,
            hierarchy_output=hierarchy_dict,
            action_recommendation=action_rec,
            narrator_insights=narrator_texts,
            scenario_disclosure=ScenarioDisclosureOut(**disclosure_dict),
            llm_narrative=None,
            as_of=as_of,
            snapshot_id=snapshot_id,
            ticker_analysis=analysis_ctx.ticker_analysis,
            market_beat=core_beat,
        )

    ensemble_out = None
    conformal_out = None
    bull_base_bear_out: list[BullBaseBearOut] = []
    global_macro_out = None
    track_record_out = None
    live_direction_accuracy_out = None
    market_beat_out: dict[str, Any] | None = None

    try:
        from app.schemas.forecast import BocpdForecastOut
        from app.services.forecast.adaptive_conformal import adaptive_conformal_interval
        from app.services.forecast.bocpd import combine_bocpd_with_hmm
        from app.services.forecast.ensemble import MODEL_FAMILY_LABELS, get_ensemble_forecast_engine
        from app.services.forecast.global_macro_view import get_global_macro_view_builder
        from app.services.forecast.symbol_horizon import horizon_for_symbol
        from app.services.forecast.live_accuracy import rolling_live_direction_accuracy
        from app.services.forecast.scenario_framing import build_bull_base_bear
        from app.services.market_data.series_loader import load_forecast_price_series
        from app.services.regime.engine import RegimeEngine
        from app.services.track_record.calibration_chart import build_track_record_chart_data
        from app.utils.wilson_ci import format_accuracy_with_ci_ru

        prices, _volumes, _src = await load_forecast_price_series(
            db, instrument.id, instrument.symbol, persist=False
        )
        momentum_score = hierarchy.point_forecast.momentum_score if hierarchy.point_forecast else None
        horizon_days = horizon_for_symbol(prices, symbol=instrument.symbol)
        live_acc = await rolling_live_direction_accuracy(
            db,
            symbol=instrument.symbol,
            horizon_days=horizon_days,
        )
        live_direction_accuracy_out = LiveDirectionAccuracyOut(
            accuracy=live_acc.accuracy,
            sample_size=live_acc.sample_size,
            ci_low=live_acc.ci_low,
            ci_high=live_acc.ci_high,
            horizon_days=live_acc.horizon_days,
            window_days=live_acc.window_days,
            formatted_ru=format_accuracy_with_ci_ru(
                live_acc.accuracy,
                ci_low=live_acc.ci_low,
                ci_high=live_acc.ci_high,
                sample_size=live_acc.sample_size,
            ),
        )

        ensemble = get_ensemble_forecast_engine().compute(
            prices,
            symbol=instrument.symbol,
            momentum_score=momentum_score,
            calibrated_confidence=hierarchy.calibrated_confidence,
            live_direction_accuracy=live_acc.accuracy,
            live_accuracy_sample_size=live_acc.sample_size,
            horizon_days=horizon_days,
        )
        ensemble_out = EnsembleForecastOut(
            median_return=ensemble.median_return,
            direction_consensus=ensemble.direction_consensus,
            models_agreeing=ensemble.models_agreeing,
            models_total=ensemble.models_total,
            insufficient_history=ensemble.insufficient_history,
            history_bars=ensemble.history_bars,
            direction_suppressed=ensemble.direction_suppressed,
            suppression_message_ru=ensemble.suppression_message_ru,
            component_models=[
                EnsembleModelOut(
                    family=m.family.value,
                    family_label=MODEL_FAMILY_LABELS.get(m.family.value, (m.family.value, m.family.value))[0],
                    family_label_ru=MODEL_FAMILY_LABELS.get(m.family.value, (m.family.value, m.family.value))[1],
                    direction=m.direction,
                    expected_return=m.expected_return,
                    weight=m.weight,
                    recent_accuracy=m.recent_accuracy,
                    available=m.available,
                    note=m.note,
                )
                for m in ensemble.component_models
            ],
            engine_overlays=ensemble.engine_overlays,
        )

        if not ensemble.insufficient_history:
            conformal = adaptive_conformal_interval(
                prices,
                ensemble.median_return,
                symbol=instrument.symbol,
            )
            conformal_out = ConformalIntervalOut(**conformal.to_dict())
            try:
                hmm = RegimeEngine().classify_instrument(list(prices))
                bocpd = combine_bocpd_with_hmm(
                    prices,
                    hmm.dominant_regime,
                    hmm_confidence=float(hmm.confidence),
                )
                if ensemble_out is not None:
                    ensemble_out.bocpd = BocpdForecastOut(**bocpd.to_dict())
                    if bocpd.regime_uncertain and not ensemble.direction_suppressed:
                        ensemble_out.suppression_message_ru = (
                            (ensemble_out.suppression_message_ru or "")
                            + (" · " if ensemble_out.suppression_message_ru else "")
                            + "режим неопределён (BOCPD≠HMM)"
                        ).strip(" ·")
            except Exception:
                raise

        narrative_probs: dict[str, float] = {}
        if hierarchy.scenario_forecast:
            for s in hierarchy.scenario_forecast.scenarios:
                if s.scenario_type in {"pessimistic", "realistic", "optimistic", "classic"}:
                    narrative_probs[s.scenario_type] = s.probability
                elif s.name in {"pessimistic", "realistic", "optimistic", "classic"}:
                    narrative_probs[s.name] = s.probability

        stress_items = hierarchy.scenario_forecast.scenarios if hierarchy.scenario_forecast else ()
        bbb = build_bull_base_bear(
            narrative_scenarios=narrative_probs or None,
            stress_scenarios=stress_items,
            median_return=ensemble.median_return,
            ensemble_bull_return=conformal_out.upper_70 if conformal_out else None,
            ensemble_bear_return=conformal_out.lower_70 if conformal_out else None,
        )
        bull_base_bear_out = [BullBaseBearOut(**s.to_dict()) for s in bbb]

        macro_view = await asyncio.wait_for(
            get_global_macro_view_builder().build(
                db,
                factor_exposures=factor_exposures,
                macro_indicators=macro or None,
            ),
            timeout=_FORECAST_UPGRADE_LAYERS_TIMEOUT_SEC,
        )
        global_macro_out = GlobalMacroViewOut(**macro_view.to_dict())

        chart_data = build_track_record_chart_data()
        track_record_out = TrackRecordChartOut(**chart_data.to_dict())

        try:
            from app.services.forecast.excess_track import rolling_excess_track
            from app.services.forecast.fund_news_extras import collect_symbol_extras
            from app.services.forecast.market_beat import market_beat_from_db
            from app.services.news.sentiment_aggregate import fetch_finbert_sentiment_map

            extras = await collect_symbol_extras(instrument.symbol)
            sentiment_map = await fetch_finbert_sentiment_map(db, [instrument.symbol])
            excess_live = await rolling_excess_track(db, symbol=instrument.symbol, horizon=20)
            live_p = excess_live.get("accuracy")
            live_n = int(excess_live.get("sample_size") or 0)
            if live_n < 8:
                live_p = live_acc.accuracy
                live_n = live_acc.sample_size
            market_beat_out = await market_beat_from_db(
                db,
                instrument.symbol,
                extras=extras,
                news_sentiment=float(sentiment_map.get(instrument.symbol, 0.0)),
                live_accuracy=live_p,
                live_n=live_n,
            )
        except Exception as exc:
            logger.debug("market_beat skipped", symbol=instrument.symbol, error=str(exc))

        engines = list(structured.engines_used or [])
        for eng in ("EnsembleForecast", "ConformalIntervals", "GlobalMacroView"):
            if eng not in engines:
                engines.append(eng)
        structured = StructuredForecastSections(
            **{**structured.model_dump(), "engines_used": engines}
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Forecast upgrade layers timed out",
            symbol=instrument.symbol,
            timeout_sec=_FORECAST_UPGRADE_LAYERS_TIMEOUT_SEC,
        )
        try:
            await db.rollback()
        except Exception:
            logger.warning("Forecast upgrade rollback failed", symbol=instrument.symbol)
    except Exception as exc:
        logger.warning("Forecast upgrade layers failed", symbol=instrument.symbol, error=str(exc))
        try:
            await db.rollback()
        except Exception:
            logger.warning("Forecast upgrade rollback failed", symbol=instrument.symbol)

    if include_llm and include_narrative:
        try:
            llm_narrative, disclosure_dict, structured = await asyncio.wait_for(
                _apply_forecast_llm_narrative(
                    db,
                    symbol=instrument.symbol,
                    hierarchy=hierarchy,
                    disclosure_dict=disclosure_dict,
                    structured=structured,
                    track_record_out=track_record_out,
                    live_direction_accuracy_out=live_direction_accuracy_out,
                ),
                timeout=_FORECAST_LLM_NARRATIVE_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Forecast LLM narrative timed out",
                symbol=instrument.symbol,
                timeout_sec=_FORECAST_LLM_NARRATIVE_TIMEOUT_SEC,
            )
        except Exception as exc:
            logger.warning("Forecast LLM narrative hook failed", symbol=instrument.symbol, error=str(exc))

    try:
        hierarchy_dict = hierarchy.to_dict()
    except Exception as exc:
        logger.warning("Hierarchy to_dict failed", symbol=instrument.symbol, error=str(exc))
        hierarchy_dict = {
            "symbol": instrument.symbol,
            "instrument_id": instrument.id,
            "calibrated_confidence": hierarchy.calibrated_confidence,
        }

    try:
        return ForecastOut(
        symbol=instrument.symbol,
        instrument_id=instrument.id,
        dominant_regime=hierarchy.global_regime.dominant_regime if hierarchy.global_regime else None,
        regime_distribution=(
            hierarchy.sector_regime.regime.distribution if hierarchy.sector_regime else {}
        ),
        composite_risk_score=hierarchy.risk_forecast.instrument_metrics.get(
            "composite_risk_score", 0.0
        ),
        confidence=hierarchy.calibrated_confidence,
        risk_flags=list(hierarchy.risk_forecast.breached_metrics),
        factor_exposures=factor_exposures,
        probability_map=probability_map,
        metric_validity=metric_validity,
        data_quality=data_quality,
        forecast_explanation=snapshot.forecast_explanation if snapshot else None,
        regime_explanation=snapshot.regime_explanation if snapshot else None,
        risk_explanation=snapshot.risk_explanation if snapshot else None,
        risk_engine_metrics=risk_metrics,
        source_metrics=snapshot.source_metrics if snapshot else {},
        structured=structured,
        hierarchy_output=hierarchy_dict,
        action_recommendation=(
            hierarchy.action_forecast.recommendation.value
            if hierarchy.action_forecast and hierarchy.action_forecast.recommendation
            else None
        ),
        narrator_insights=narrator_texts,
        scenario_disclosure=ScenarioDisclosureOut(**disclosure_dict),
        llm_narrative=llm_narrative,
        as_of=as_of,
        snapshot_id=snapshot_id,
        ticker_analysis=analysis_ctx.ticker_analysis,
        ensemble_forecast=ensemble_out,
        conformal_intervals=conformal_out,
        bull_base_bear=bull_base_bear_out,
        global_macro=global_macro_out,
        track_record_chart=track_record_out,
        live_direction_accuracy=live_direction_accuracy_out,
        market_beat=market_beat_out,
        )
    except Exception as exc:
        logger.warning(
            "Forecast response assembly failed",
            symbol=instrument.symbol,
            error=str(exc)[:400],
        )
        raise HTTPException(
            status_code=503,
            detail=_friendly_forecast_detail(exc, instrument.symbol),
        ) from exc


@router.get("/daily", response_model=DailyForecastOut)
async def get_daily_forecasts(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> DailyForecastOut:
    """Return latest persisted daily forecast snapshots for the effective watchlist."""
    symbols = await get_effective_watchlist(db, email)
    snapshots = await latest_snapshots_for_symbols(db, symbols)

    items: list[DailyForecastItem] = []
    for snap in snapshots:
        payload = snap.payload or {}
        items.append(
            DailyForecastItem(
                symbol=snap.symbol,
                instrument_id=snap.instrument_id,
                as_of=snap.snapshot_date,
                snapshot_id=snap.id,
                payload=_structured_from_payload(payload),
                composite_risk_score=float(payload.get("composite_risk_score", 0.0)),
                confidence=float(payload.get("confidence", 0.0)),
            )
        )

    return DailyForecastOut(items=items, count=len(items))


_GLOBAL_MACRO_CACHE: dict = {}
_RANKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_RANKS_TTL_SEC = 900.0


@router.get("/ranks")
async def get_market_beat_ranks(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Watchlist ∪ tier B ranked by 20-session beat-benchmark score (trees = who)."""
    from app.services.forecast.cs_cache import ranks_from_returns, save_cs_features
    from app.services.forecast.fund_news_extras import collect_symbol_extras
    from app.services.forecast.market_beat import market_beat_from_db
    from app.services.forecast.tier_b_universe import daily_retrain_symbols

    import asyncio
    import time as _time

    watchlist = await get_effective_watchlist(db, email)
    symbols = daily_retrain_symbols(watchlist)[:40]
    cache_key = ",".join(symbols)
    hit = _RANKS_CACHE.get(cache_key)
    if hit and _time.monotonic() - hit[0] < _RANKS_TTL_SEC:
        return hit[1]

    from app.db.session import AsyncSessionLocal

    sem = asyncio.Semaphore(6)

    async def _one(sym: str) -> dict[str, Any] | None:
        # Was a sequential loop over 40 symbols with network calls each: well over a minute.
        # Each symbol gets its own session (one AsyncSession cannot be shared concurrently)
        # and a time cap, so one slow source cannot hold the page.
        async with sem:
            try:
                async with AsyncSessionLocal() as sdb:
                    extras = await asyncio.wait_for(collect_symbol_extras(sym), timeout=8)
                    return await asyncio.wait_for(market_beat_from_db(sdb, sym, extras=extras), timeout=12)
            except Exception as exc:  # noqa: BLE001
                logger.debug("rank skipped", symbol=sym, error=str(exc)[:160])
                return None

    items: list[dict[str, Any]] = [r for r in await asyncio.gather(*[_one(s) for s in symbols]) if r]
    try:
        rmap = {r["symbol"]: float(r.get("p_beat_20") or 0.5) for r in items}
        ranked = ranks_from_returns(rmap)
        cache = {
            sym: {
                "cs_ret5_rank": float((ranked.get(sym) or {}).get("rank") or 0.0),
                "cs_ret21_rank": float((ranked.get(sym) or {}).get("rank") or 0.0),
                "cs_breadth": float(next(iter(ranked.values()), {}).get("breadth") or 0.0),
            }
            for sym in rmap
        }
        save_cs_features(cache)
    except Exception:
        raise
    items.sort(key=lambda row: int(row.get("score_20") or 0), reverse=True)
    book = None
    try:
        from app.services.forecast.daily_book import (
            build_daily_book,
            persist_daily_book,
            persist_rank_index,
        )

        persist_rank_index(items)
        book = build_daily_book(items)
        persist_daily_book(book)
        from app.services.forecast.daily_book import excess_history
        from app.services.forecast.purged_cv import deflated_sharpe_ratio

        hist = excess_history()
        if book is not None:
            book["deflated_sharpe"] = deflated_sharpe_ratio(hist, n_trials=max(len(items), 1))
    except Exception:
        book = None
    tear = None
    try:
        from app.services.forecast.tear_sheet import load_latest_tear_sheet

        tear = load_latest_tear_sheet()
    except Exception:
        tear = None
    payload = {
        "items": items,
        "count": len(items),
        "daily_book": book,
        "tear_sheet": tear,
        "note_ru": (
            "Деревья ранжируют кого смотреть. PPO в карточке бумаги говорит когда. "
            "Ярус C (весь рынок) — когда будут платные вендоры."
        ),
    }
    if items:
        _RANKS_CACHE[cache_key] = (_time.monotonic(), payload)
    return payload


@router.get("/health", response_model=ForecastHealthOut)
async def forecast_health(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> ForecastHealthOut:
    """Lightweight self-test — runs hierarchy on SPY and returns full output."""
    instrument = await _resolve_instrument(db, "SPY")
    checks: dict[str, str] = {"instrument": "ok"}

    try:
        hierarchy = await get_hierarchy_orchestrator().get_forecast(
            db,
            instrument.id,
            symbol=instrument.symbol,
            include_narrative=False,
            use_cache=False,
        )
        checks["hierarchy"] = "ok"
        hierarchy_dict = hierarchy.to_dict()
    except Exception as exc:
        logger.error("Forecast health check failed", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=_FORECAST_USER_MESSAGE,
        ) from exc

    sli: dict[str, Any] = {}
    try:
        from app.services.forecast.sli import model_sli

        sli = model_sli()
        checks["model_sli"] = "ok" if (sli.get("sidecar_count") or 0) >= 0 else "empty"
    except Exception:
        checks["model_sli"] = "skip"

    return ForecastHealthOut(
        status="ok",
        symbol=instrument.symbol,
        instrument_id=instrument.id,
        hierarchy_output=hierarchy_dict,
        checks=checks,
        sli=sli,
    )


@router.get("/market", response_model=MarketForecastOut)
async def get_market_forecast(
    explain: bool = Query(False, description="Generate the paid AI text for the market outlook"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> MarketForecastOut:
    """Aggregate macro/global regime and sector rotation outlook."""
    try:
        payload = await build_market_forecast(db)
        try:
            from app.services.forecast_log.emit import emit_market

            emit_market(payload if isinstance(payload, dict) else {})
            from app.services.forecast_core.service import for_market

            for_market("IMOEX")
        except Exception:
            logger.debug("forecast_log market emit skipped")
    except Exception as exc:
        logger.warning("Market forecast failed", error=str(exc))
        raise HTTPException(status_code=503, detail=_FORECAST_USER_MESSAGE) from exc

    macro_block = None
    try:
        from app.schemas.macro_registry import MacroBlockOut
        from app.services.macro_registry.report_engine import MacroReportEngine
        from app.services.macro_registry.service import load_macro_snapshot

        indicators = await load_macro_snapshot(db)
        missing: list[str] = []
        for key in ("vix", "cpi", "rate_cb", "dxy", "oil_brent", "unemployment"):
            if key not in indicators:
                missing.append(f"macro_series_normalized.{key}")
        for key in ("rate_cb_ca", "cpi_ca", "unemployment_ca", "usdcad"):
            if key not in indicators:
                missing.append(f"macro_series_normalized.{key} (Canada — optional)")
        for key in (
            "wb_world_gdp_growth",
            "wb_us_gdp_growth",
            "wb_cn_gdp_growth",
            "wb_ru_gdp_growth",
            "wb_us_inflation",
            "wb_us_current_account",
        ):
            if key not in indicators:
                missing.append(f"macro_series_normalized.{key} (World Bank — optional)")
        for key in ("eu_gdp_growth", "eu_gdp_yoy_q", "eu_hicp_yoy", "eu_unemployment"):
            if key not in indicators:
                missing.append(f"macro_series_normalized.{key} (Eurostat — optional)")
        if "credit_spread" not in indicators:
            missing.append("credit_spread.hy_vs_gov (FRED HY OAS + 10Y Treasury)")
        report = await MacroReportEngine().generate(db, mode="daily")
        macro_block = MacroBlockOut(
            indicators=indicators,
            report_mode="daily",
            missing_resources=missing,
            upcoming_releases=report.get("upcoming_releases", []),
            as_of=_parse_as_of(payload["as_of"]),
        ).model_dump()
    except Exception as exc:
        logger.warning("Macro block build failed", error=str(exc))

    market_llm_narrative = None
    market_disclosure = dict(payload.get("scenario_disclosure") or {})
    try:
        if not _ai_allowed(explain):
            raise _AiNotRequested
        from app.services.forecast.forecast_narrative_llm import (
            apply_llm_narrative_to_disclosure,
            try_llm_market_forecast_narrative,
        )

        market_llm_narrative = await asyncio.wait_for(
            try_llm_market_forecast_narrative(
                disclosure=market_disclosure,
                global_regime=payload.get("global_regime") or {},
                macro_indicators=payload.get("macro_indicators"),
                market_outlook=payload.get("market_outlook"),
                sector_rotation=payload.get("sector_rotation"),
                market_prediction_summary=payload.get("market_prediction_summary"),
                db=db,
            ),
            timeout=_FORECAST_LLM_NARRATIVE_TIMEOUT_SEC,
        )
        if market_llm_narrative:
            market_disclosure = apply_llm_narrative_to_disclosure(
                market_disclosure,
                market_llm_narrative,
            )
            summary_payload = dict(payload.get("market_prediction_summary") or {})
            paras = [p.strip() for p in market_llm_narrative.split("\n") if p.strip()]
            if paras:
                summary_payload["paragraphs"] = paras
            payload["market_prediction_summary"] = summary_payload
    except _AiNotRequested:
        pass
    except asyncio.TimeoutError:
        logger.warning(
            "Market forecast LLM narrative timed out",
            timeout_sec=_FORECAST_LLM_NARRATIVE_TIMEOUT_SEC,
        )
    except Exception as exc:
        logger.warning("Market LLM narrative hook failed", error=str(exc))

    return MarketForecastOut(
        as_of=_parse_as_of(payload["as_of"]) or datetime.utcnow(),
        global_regime=payload["global_regime"],
        market_outlook=payload["market_outlook"],
        sector_rotation=payload["sector_rotation"],
        calibrated_probabilities=payload["calibrated_probabilities"],
        macro_indicators=payload["macro_indicators"],
        macro_block=macro_block,
        market_prediction_summary=MarketPredictionSummaryOut(
            **payload.get("market_prediction_summary", {}),
        ),
        scenario_disclosure=ScenarioDisclosureOut(
            **market_disclosure,
        ),
        llm_narrative=market_llm_narrative,
    )


@router.get("/global-macro", response_model=GlobalMacroViewOut)
async def get_global_macro_view(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> GlobalMacroViewOut:
    """Cross-asset correlation matrix, regime map, factor rotation."""
    from app.services.forecast.global_macro_view import get_global_macro_view_builder

    import time as _time

    # Same market-wide picture for every user; ~14 s to build on the server. Cache 10 minutes.
    hit = _GLOBAL_MACRO_CACHE.get("v")
    if hit and _time.monotonic() - hit[0] < 600:
        return hit[1]
    try:
        view = await get_global_macro_view_builder().build(db)
        out = GlobalMacroViewOut(**view.to_dict())
        if view.to_dict().get("regime_map"):
            _GLOBAL_MACRO_CACHE["v"] = (_time.monotonic(), out)
        return out
    except Exception as exc:
        logger.warning("Global macro view failed", error=str(exc))
        raise HTTPException(status_code=503, detail=_FORECAST_USER_MESSAGE) from exc


@router.get("/track-record/chart", response_model=TrackRecordChartOut)
async def get_track_record_chart(
    email: str = Depends(get_current_user_email),
) -> TrackRecordChartOut:
    """Calibration reliability diagram and rolling accuracy for Forecast UI."""
    from app.services.track_record.calibration_chart import build_track_record_chart_data

    chart = build_track_record_chart_data()
    return TrackRecordChartOut(**chart.to_dict())


def _direction_from_sign(sign: Any) -> str:
    try:
        value = int(sign)
    except (TypeError, ValueError):
        return "neutral"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "neutral"


def _as_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _calibrated_confidence(hierarchy: Any, payload: dict[str, Any], point: dict[str, Any] | None) -> float | None:
    """Same number as Forecast desk header: calibrated, then last-resort fallbacks."""
    if isinstance(hierarchy, dict):
        value = _as_float(hierarchy.get("calibrated_confidence"))
        if value is not None:
            return value
    value = _as_float(payload.get("calibrated_confidence"))
    if value is not None:
        return value
    value = _as_float(payload.get("confidence"))
    if value is not None:
        return value
    if isinstance(point, dict):
        for key in ("confidence", "momentum_score"):
            value = _as_float(point.get(key))
            if value is not None:
                return value
    return None


def _signal_from_payload(symbol: str, payload: dict) -> dict[str, Any] | None:
    hierarchy = payload.get("hierarchy_output") or payload.get("hierarchy") or {}
    point = hierarchy.get("point_forecast") if isinstance(hierarchy, dict) else None
    sign = None
    if isinstance(point, dict):
        sign = point.get("expected_return_sign")
        if sign is None and point.get("direction") in {"up", "down", "neutral"}:
            conf = _calibrated_confidence(hierarchy, payload, point)
            if conf is None:
                return None
            return {
                "symbol": symbol.upper(),
                "direction": point["direction"],
                "confidence": conf,
                "source": "forecast_engine",
            }
    if sign is None:
        sign = payload.get("expected_return_sign") or payload.get("direction_consensus")
    conf = _calibrated_confidence(
        hierarchy if isinstance(hierarchy, dict) else None,
        payload,
        point if isinstance(point, dict) else None,
    )
    if sign is None and conf is None:
        return None
    return {
        "symbol": symbol.upper(),
        "direction": _direction_from_sign(sign),
        "confidence": conf if conf is not None else 0.0,
        "source": "forecast_engine",
    }


@router.get("/signals")
async def get_forecast_signals(
    symbols: str = Query(..., description="Comma-separated tickers"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """ML direction + confidence from the existing Forecast engine (no new model)."""
    raw = [part.strip().upper() for part in symbols.split(",") if part.strip()]
    uniq: list[str] = []
    seen: set[str] = set()
    for sym in raw[:100]:
        if sym not in seen:
            seen.add(sym)
            uniq.append(sym)

    snapshots = await latest_snapshots_for_symbols(db, uniq)
    by_symbol = {snap.symbol.upper(): snap for snap in snapshots}
    items: list[dict] = []
    missing: list[str] = []

    for sym in uniq:
        snap = by_symbol.get(sym)
        signal = _signal_from_payload(sym, snap.payload or {}) if snap is not None else None
        if signal:
            items.append(signal)
        else:
            missing.append(sym)

    sem = asyncio.Semaphore(3)

    async def _live(sym: str) -> dict | None:
        async with sem:
            try:
                instrument = await _resolve_instrument(db, sym)
                orchestrator = get_hierarchy_orchestrator()
                hierarchy = await orchestrator.get_forecast(
                    db,
                    instrument.id,
                    symbol=instrument.symbol,
                    include_narrative=False,
                    use_cache=True,
                )
                sign = None
                if hierarchy.point_forecast is not None:
                    sign = hierarchy.point_forecast.expected_return_sign
                conf = hierarchy.calibrated_confidence
                return {
                    "symbol": instrument.symbol,
                    "direction": _direction_from_sign(sign),
                    "confidence": float(conf) if conf is not None else None,
                    "source": "forecast_engine",
                }
            except Exception as exc:
                logger.debug("Forecast signal skipped", symbol=sym, error=str(exc))
                return {
                    "symbol": sym,
                    "direction": "neutral",
                    "confidence": None,
                    "source": "forecast_engine",
                    "reason": "unavailable",
                }

    live = await asyncio.gather(*[_live(sym) for sym in missing])
    items.extend([row for row in live if row])
    order = {sym: i for i, sym in enumerate(uniq)}
    items.sort(key=lambda row: order.get(row["symbol"], 999))
    try:
        from app.services.forecast_log.emit import emit_forecast

        for row in items:
            emit_forecast(
                {
                    "symbol": row.get("symbol"),
                    "instrument_id": row.get("symbol"),
                    "confidence": row.get("confidence") or 0.5,
                    "action_recommendation": row.get("direction"),
                },
                section="forecast_signals",
            )
    except Exception:
        logger.debug("forecast_log signals emit skipped")
    return {"items": items, "count": len(items)}


@router.get("/{symbol}/narrative", response_model=ForecastNarrativeOut)
async def get_forecast_narrative(
    symbol: str,
    explain: bool = Query(False, description="Generate the paid AI text (user pressed «Пояснение ИИ»)"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> ForecastNarrativeOut:
    """LLM-only narrative layer — uses cached hierarchy; pair with GET /forecast/{symbol}?include_llm=false."""
    instrument = await _resolve_instrument(db, symbol)
    orchestrator = get_hierarchy_orchestrator()

    try:
        hierarchy = await orchestrator.get_forecast(
            db,
            instrument.id,
            symbol=instrument.symbol,
            include_narrative=True,
            use_cache=True,
        )
    except Exception as exc:
        logger.warning("Narrative hierarchy failed", symbol=instrument.symbol, error=str(exc))
        raise HTTPException(status_code=503, detail=_friendly_forecast_detail(exc, instrument.symbol)) from exc

    macro: dict = {}
    macro_bundle: dict = {}
    try:
        from app.services.macro_registry.service import load_macro_snapshot_bundle

        macro_bundle = await load_macro_snapshot_bundle(db)
        macro = macro_bundle.get("indicators") or {}
    except Exception:
        macro = {}

    disclosure = ScenarioDisclosureNarrator().from_hierarchy_dict(
        hierarchy.to_dict(),
        macro=macro,
        macro_bundle=macro_bundle,
        global_result=hierarchy.global_regime,
        rotation_scores=(
            (hierarchy.sector_regime.rotation,) if hierarchy.sector_regime else ()
        ),
        symbol=instrument.symbol,
        scope="symbol",
    )
    disclosure_dict = disclosure.to_dict()
    structured = StructuredForecastSections(
        market_outlook=[],
        actionable_summary=[],
        engines_used=[],
    )

    track_record_out = None
    live_direction_accuracy_out = None
    try:
        from app.services.forecast.live_accuracy import rolling_live_direction_accuracy
        from app.services.forecast.symbol_horizon import horizon_for_symbol
        from app.services.market_data.series_loader import load_forecast_price_series
        from app.services.track_record.calibration_chart import build_track_record_chart_data

        prices, _volumes, _src = await load_forecast_price_series(
            db, instrument.id, instrument.symbol, persist=False
        )
        horizon_days = horizon_for_symbol(prices, symbol=instrument.symbol)
        live_acc = await rolling_live_direction_accuracy(
            db,
            symbol=instrument.symbol,
            horizon_days=horizon_days,
        )
        from app.utils.wilson_ci import format_accuracy_with_ci_ru

        live_direction_accuracy_out = LiveDirectionAccuracyOut(
            accuracy=live_acc.accuracy,
            sample_size=live_acc.sample_size,
            ci_low=live_acc.ci_low,
            ci_high=live_acc.ci_high,
            horizon_days=live_acc.horizon_days,
            window_days=live_acc.window_days,
            formatted_ru=format_accuracy_with_ci_ru(
                live_acc.accuracy,
                ci_low=live_acc.ci_low,
                ci_high=live_acc.ci_high,
                sample_size=live_acc.sample_size,
            ),
        )
        chart_data = build_track_record_chart_data()
        track_record_out = TrackRecordChartOut(**chart_data.to_dict())
    except Exception as exc:
        logger.debug("Narrative track-record skipped", symbol=instrument.symbol, error=str(exc))

    llm_narrative = None
    try:
        if not _ai_allowed(explain):
            raise _AiNotRequested
        llm_narrative, disclosure_dict, structured = await asyncio.wait_for(
            _apply_forecast_llm_narrative(
                db,
                symbol=instrument.symbol,
                hierarchy=hierarchy,
                disclosure_dict=disclosure_dict,
                structured=structured,
                track_record_out=track_record_out,
                live_direction_accuracy_out=live_direction_accuracy_out,
            ),
            timeout=_FORECAST_LLM_NARRATIVE_TIMEOUT_SEC,
        )
    except _AiNotRequested:
        pass
    except asyncio.TimeoutError:
        logger.warning(
            "Forecast narrative endpoint timed out",
            symbol=instrument.symbol,
            timeout_sec=_FORECAST_LLM_NARRATIVE_TIMEOUT_SEC,
        )
        raise HTTPException(
            status_code=503,
            detail="Пояснение ИИ временно недоступно — повторите через минуту.",
        ) from None
    except Exception as exc:
        logger.warning("Forecast narrative endpoint failed", symbol=instrument.symbol, error=str(exc))
        raise HTTPException(status_code=503, detail=_friendly_forecast_detail(exc, instrument.symbol)) from exc

    if not llm_narrative and not _ai_allowed(explain):
        # Template text only (the user has not pressed «Пояснение ИИ»): this is a normal
        # answer, not an error. Answering 503 here showed an AI failure on every page load.
        return ForecastNarrativeOut(
            symbol=instrument.symbol,
            llm_narrative=None,
            scenario_disclosure=ScenarioDisclosureOut(**disclosure_dict),
            actionable_summary=list(structured.actionable_summary or []),
        )

    if not llm_narrative:
        raise HTTPException(
            status_code=503,
            detail="Пояснение ИИ временно недоступно — повторите через минуту.",
        )

    return ForecastNarrativeOut(
        symbol=instrument.symbol,
        llm_narrative=llm_narrative,
        scenario_disclosure=ScenarioDisclosureOut(**disclosure_dict),
        actionable_summary=list(structured.actionable_summary or []),
    )


def attach_forecast_core(out: ForecastOut, symbol: str) -> ForecastOut:
    """UI numbers come from forecast_core.for_ui, not a discarded side call."""
    try:
        from app.services.forecast_core.service import for_ui

        core = for_ui(symbol)
    except Exception:
        return out
    metrics = dict(out.source_metrics or {})
    metrics["forecast_core"] = core
    updates: dict[str, Any] = {"source_metrics": metrics}
    if core.get("probability") is not None:
        updates["confidence"] = float(core["probability"])
        pmap = dict(out.probability_map or {})
        pmap["forecast_core"] = float(core["probability"])
        updates["probability_map"] = pmap
    if core.get("data_status"):
        quality = dict(out.data_quality or {})
        quality["forecast_core"] = str(core["data_status"])
        updates["data_quality"] = quality
    return out.model_copy(update=updates)


@router.get("/{symbol}", response_model=ForecastOut)
async def get_forecast(
    symbol: str,
    use_snapshot: bool = Query(False, description="Return latest persisted daily snapshot if available"),
    include_narrative: bool = Query(True, description="Include ensemble upgrade layers and narrator"),
    include_llm: bool = Query(False, description="Include the paid AI narrative (only on explicit request)"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> ForecastOut:
    """Aggregate hierarchy forecast via PredictionHierarchyOrchestrator (Prompt 38)."""
    instrument = await _resolve_instrument(db, symbol)
    out = await _build_forecast_response(
        db,
        instrument,
        use_snapshot=use_snapshot,
        include_narrative=include_narrative,
        include_llm=include_llm,
    )
    try:
        from app.services.forecast_log.emit import emit_forecast

        emit_forecast(out, section="forecast")
    except Exception:
        logger.debug("forecast_log emit skipped", symbol=instrument.symbol)
    return attach_forecast_core(out, instrument.symbol)
