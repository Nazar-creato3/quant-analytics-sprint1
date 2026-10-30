"""Daily forecast snapshot Celery task."""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.tasks.celery_app import celery_app
from app.tasks.data_ingestion import _run_async

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.forecast.refresh_daily_forecasts_task")
def refresh_daily_forecasts_task(tickers: list[str] | None = None) -> dict[str, Any]:
    """Build and persist daily forecast snapshots for watchlist symbols."""
    from app.core.config import settings
    from app.utils.healthchecks import ping_healthcheck

    tickers_list = tickers or settings.default_watchlist_list
    try:
        result = _run_async(_async_refresh_daily_forecasts(tickers_list))
        ping_healthcheck(settings.HC_PING_FORECAST, success=result.get("status") != "failed")
        return result
    except Exception as exc:
        logger.exception("Daily forecast refresh failed", error=str(exc))
        ping_healthcheck(settings.HC_PING_FORECAST, success=False)
        return {"status": "failed", "symbols": len(tickers_list), "reason": str(exc)}


async def _async_refresh_daily_forecasts(tickers: list[str]) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.forecast.daily_builder import get_daily_forecast_builder
    from app.services.forecast.snapshot_repository import upsert_daily_snapshot
    from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator
    from app.services.settings.watchlist import get_effective_watchlist

    builder = get_daily_forecast_builder()
    orchestrator = get_hierarchy_orchestrator()
    saved = 0
    skipped: list[str] = []

    async with AsyncSessionLocal() as session:
        effective = tickers or await get_effective_watchlist(session)
        from app.services.instrument.resolver import resolve_or_create_instrument

        for symbol in effective:
            sym = symbol.strip().upper()
            if not sym:
                continue
            try:
                instrument = await resolve_or_create_instrument(session, sym)
            except ValueError:
                skipped.append(sym)
                continue
            try:
                hierarchy = await orchestrator.get_forecast(
                    session,
                    instrument.id,
                    symbol=instrument.symbol,
                    include_narrative=True,
                    use_cache=False,
                )
                payload = await builder.build(
                    session,
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                )
                payload["hierarchy_output"] = hierarchy.to_dict()
                payload["calibrated_confidence"] = hierarchy.calibrated_confidence
                payload["action_recommendation"] = hierarchy.action_forecast.recommendation.value
                from app.services.forecast.snapshot_direction import enrich_payload_predicted_direction

                payload = await enrich_payload_predicted_direction(
                    session,
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    hierarchy=hierarchy,
                    payload=payload,
                )
                if "horizon_days" not in payload:
                    payload["horizon_days"] = (
                        hierarchy.interval_forecast.horizon_days
                        if hierarchy.interval_forecast
                        else 10
                    )
                try:
                    from app.services.forecast.adaptive_conformal import adaptive_conformal_interval
                    from app.services.forecast.ensemble import get_ensemble_forecast_engine
                    from app.services.market_data.series_loader import load_forecast_price_series

                    prices, _vol, _src = await load_forecast_price_series(
                        session, instrument.id, instrument.symbol, persist=False
                    )
                    from app.services.forecast.symbol_horizon import horizon_for_symbol

                    selected_horizon = int(payload["horizon_days"])
                    ensemble = get_ensemble_forecast_engine().compute(
                        prices,
                        symbol=instrument.symbol,
                        momentum_score=hierarchy.point_forecast.momentum_score
                        if hierarchy.point_forecast
                        else None,
                        calibrated_confidence=hierarchy.calibrated_confidence,
                        horizon_days=selected_horizon,
                    )
                    try:
                        from app.services.forecast.excess_labels import benchmark_symbol_for
                        from app.services.forecast.market_beat import market_beat_from_prices
                        from app.services.market_data.bars import get_bars_for_chart

                        bars = await get_bars_for_chart(session, instrument.symbol, "1d", 260, force_refresh=False)
                        closes_b = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
                        highs_b = [float(b.high) for b in bars if getattr(b, "high", None) is not None]
                        lows_b = [float(b.low) for b in bars if getattr(b, "low", None) is not None]
                        vols_b = [float(getattr(b, "volume", 0) or 0) for b in bars]
                        bbars = await get_bars_for_chart(
                            session, benchmark_symbol_for(instrument.symbol), "1d", 260, force_refresh=False
                        )
                        bench_c = [float(b.close) for b in bbars if getattr(b, "close", None) is not None]
                        if len(closes_b) >= 40:
                            payload["market_beat"] = market_beat_from_prices(
                                instrument.symbol,
                                closes_b,
                                volumes=vols_b if len(vols_b) == len(closes_b) else None,
                                highs=highs_b if len(highs_b) == len(closes_b) else None,
                                lows=lows_b if len(lows_b) == len(closes_b) else None,
                                benchmark=bench_c or None,
                            )
                    except Exception as exc:
                        logger.debug("snapshot market_beat skipped", symbol=sym, error=str(exc))

                    if not ensemble.insufficient_history:
                        conformal = adaptive_conformal_interval(
                            prices,
                            ensemble.median_return,
                            symbol=instrument.symbol,
                            horizon_days=int(payload["horizon_days"]),
                        )
                        payload["conformal_intervals"] = conformal.to_dict()
                except Exception as exc:
                    logger.debug("Snapshot conformal skipped", symbol=sym, error=str(exc))
                await upsert_daily_snapshot(
                    session,
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    payload=payload,
                )
                try:
                    from app.services.forecast_log.emit import emit_forecast

                    emit_forecast(
                        {
                            "symbol": instrument.symbol,
                            "instrument_id": instrument.id,
                            "confidence": payload.get("calibrated_confidence")
                            or hierarchy.calibrated_confidence,
                            "action_recommendation": payload.get("action_recommendation")
                            or getattr(hierarchy.action_forecast, "recommendation", None),
                            "ensemble_forecast": {
                                "direction_consensus": payload.get("predicted_direction") or 0
                            },
                        },
                        section="scheduled_daily",
                    )
                except Exception:
                    raise
                saved += 1
            except Exception as exc:
                logger.warning("Forecast snapshot skipped", symbol=sym, error=str(exc))
                skipped.append(sym)

    status = "success" if saved > 0 else "empty"
    logger.info("Daily forecast refresh complete", saved=saved, skipped=len(skipped))
    result = {"status": status, "saved": saved, "skipped": skipped, "symbols": len(effective)}
    try:
        from datetime import datetime, timezone

        from app.utils.cache import cache_set

        await cache_set(
            "ops:forecast_last_refresh",
            {**result, "ts_utc": datetime.now(timezone.utc).isoformat()},
            ttl=86400,
        )
    except Exception:
        raise
    return result


@celery_app.task(name="app.tasks.forecast.resolve_forecast_snapshots_task")
def resolve_forecast_snapshots_task(limit: int = 200) -> dict[str, Any]:
    """Resolve mature forecast snapshots against realized OHLCV."""
    try:
        return _run_async(_async_resolve_forecast_snapshots(limit))
    except Exception as exc:
        logger.exception("Forecast snapshot resolution failed", error=str(exc))
        return {"status": "failed", "reason": str(exc)}


async def _async_resolve_forecast_snapshots(limit: int) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.forecast.snapshot_resolver import resolve_mature_snapshots

    async with AsyncSessionLocal() as session:
        resolved = await resolve_mature_snapshots(session, limit=limit)
    return {
        "status": "success",
        "resolved": len(resolved),
        "symbols": sorted({r.symbol for r in resolved}),
    }


@celery_app.task(name="app.tasks.forecast.retrain_forecast_models_task")
def retrain_forecast_models_task(symbols: list[str] | None = None) -> dict[str, Any]:
    """Daily rolling retrain: watchlist (tier A) ∪ liquid extras (tier B)."""
    try:
        return _run_async(_async_retrain_forecast_models(symbols))
    except Exception as exc:
        logger.exception("Forecast model retrain failed", error=str(exc))
        return {"status": "failed", "reason": str(exc)}


async def _async_retrain_forecast_models(tickers: list[str] | None) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.forecast.excess_labels import benchmark_symbol_for
    from app.services.forecast.fund_news_extras import collect_symbol_extras
    from app.services.forecast.lob_features import lob_features_from_snapshot
    from app.services.forecast.retrain import retrain_forecast_models
    from app.services.forecast.tier_b_universe import daily_retrain_symbols
    from app.services.market_data.bars import get_bars_for_chart
    from app.services.news.sentiment_aggregate import fetch_finbert_sentiment_map
    from app.services.orders.order_book import fetch_order_book
    from app.services.settings.watchlist import get_effective_watchlist

    results: list[dict[str, object]] = []
    bench_cache: dict[str, list[float]] = {}
    panel_universe: dict[str, dict[str, list[float]]] = {}
    async with AsyncSessionLocal() as session:
        if tickers:
            universe = [s.strip().upper() for s in tickers if s and s.strip()]
        else:
            watchlist = await get_effective_watchlist(session)
            universe = daily_retrain_symbols(watchlist)
        for symbol in universe:
            sym = symbol.strip().upper()
            bars = await get_bars_for_chart(session, sym, "1d", 504, force_refresh=False)
            closes = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
            highs = [float(b.high) for b in bars if getattr(b, "high", None) is not None]
            lows = [float(b.low) for b in bars if getattr(b, "low", None) is not None]
            volumes = [float(getattr(b, "volume", 0) or 0) for b in bars]
            if len(closes) < 60:
                results.append({"symbol": sym, "status": "skipped", "reason": "insufficient_bars"})
                continue
            sentiment_map = await fetch_finbert_sentiment_map(session, [sym])
            news_sentiment = float(sentiment_map.get(sym, 0.0))
            order_book_imbalance = 0.0
            try:
                book = await fetch_order_book(sym)
                lob = lob_features_from_snapshot(book)
                order_book_imbalance = float(lob.order_flow_imbalance)
            except Exception:
                raise
            extras = await collect_symbol_extras(sym)
            bar_dates = [
                str(getattr(b, "timestamp", "") or "")[:10]
                for b in bars
                if getattr(b, "close", None) is not None
            ]
            if len(bar_dates) != len(closes):
                bar_dates = []
            bench_sym = benchmark_symbol_for(sym)
            if bench_sym not in bench_cache:
                bbars = await get_bars_for_chart(session, bench_sym, "1d", 504, force_refresh=False)
                bench_cache[bench_sym] = [
                    float(b.close) for b in bbars if getattr(b, "close", None) is not None
                ]
            result = retrain_forecast_models(
                closes,
                symbol=sym,
                highs=highs,
                lows=lows,
                news_sentiment=news_sentiment,
                order_book_imbalance=order_book_imbalance,
                benchmark_closes=bench_cache.get(bench_sym),
                extras=extras,
                volumes=volumes if len(volumes) == len(closes) else None,
                dates=bar_dates or None,
            )
            panel_universe[sym] = {
                "closes": closes,
                "highs": highs,
                "lows": lows,
                "volumes": volumes if len(volumes) == len(closes) else [],
                "benchmark": bench_cache.get(bench_sym) or [],
                "dates": bar_dates,
            }
            from dataclasses import asdict

            results.append({"symbol": sym, "status": "ok", **asdict(result)})

    from app.services.forecast.symbol_horizon import refresh_symbol_horizon_cache

    price_map = {}
    async with AsyncSessionLocal() as session:
        for symbol in universe:
            sym = symbol.strip().upper()
            bars = await get_bars_for_chart(session, sym, "1d", 504, force_refresh=False)
            closes = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
            if len(closes) >= 60:
                price_map[sym] = closes
    horizons = refresh_symbol_horizon_cache(price_map, use_ensemble=True) if price_map else {}

    panel_metrics: dict[str, object] = {}
    try:
        from app.services.forecast.panel_train import train_panel_lgbm

        panel_metrics["h20"] = train_panel_lgbm(panel_universe, horizon=20)
        panel_metrics["h60"] = train_panel_lgbm(panel_universe, horizon=60)
    except Exception as exc:
        logger.warning("panel LightGBM retrain failed", error=str(exc)[:300])
        panel_metrics["error"] = str(exc)[:300]

    return {
        "status": "success",
        "universe": universe,
        "results": results,
        "symbol_horizons": horizons,
        "panel": panel_metrics,
    }


@celery_app.task(name="app.tasks.forecast.register_live_baseline_task")
def register_live_baseline_task() -> dict[str, Any]:
    """Register current live ensemble accuracy as MLflow/local baseline."""
    try:
        return _run_async(_async_register_live_baseline())
    except Exception as exc:
        logger.exception("Live baseline registration failed", error=str(exc))
        return {"status": "failed", "reason": str(exc)}


async def _async_register_live_baseline() -> dict[str, Any]:
    from sqlalchemy import Integer, cast, func, select

    from app.db.models import ForecastSnapshotResolution
    from app.db.session import AsyncSessionLocal
    from app.services.forecast.feature_store import get_forecast_feature_store
    from app.services.forecast.mlflow_registry import register_ensemble_run
    from app.services.market_data.bars import get_bars_for_chart

    symbols = ["AAPL", "MSFT", "SPY", "BTC-USD"]
    per_symbol: dict[str, dict[str, float | int]] = {}
    total_n = 0
    weighted = 0.0
    store = get_forecast_feature_store()

    async with AsyncSessionLocal() as session:
        for symbol in symbols:
            stmt = select(
                func.count().label("n"),
                func.avg(cast(ForecastSnapshotResolution.direction_hit, Integer)).label("acc"),
            ).where(ForecastSnapshotResolution.symbol == symbol)
            row = (await session.execute(stmt)).one()
            n = int(row.n or 0)
            acc = float(row.acc) if row.acc is not None and n else 0.0
            per_symbol[symbol] = {"n": n, "accuracy": acc}
            total_n += n
            weighted += acc * n
            bars = await get_bars_for_chart(session, symbol, "1d", 120, force_refresh=False)
            closes = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
            if len(closes) >= 40:
                store.materialize_from_prices(symbol, closes)

    accuracy = (weighted / total_n) if total_n else 0.0
    if total_n <= 0:
        return {"status": "ok", "reason": "нет данных", "registered": False, "per_symbol": per_symbol}
    registered = register_ensemble_run(
        model_name="ensemble_baseline_v1",
        accuracy=accuracy,
        n=total_n,
        params={"members": "arima,momentum,lightgbm,nbeats,chronos,regime,lob"},
        tags={"stage": "live_baseline"},
        promote_live=True,
        artifact_dict={"per_symbol": per_symbol, "feature_store": store.backend},
    )
    return {"status": "success", "registered": registered, "per_symbol": per_symbol}


@celery_app.task(name="app.tasks.forecast.train_stacking_meta_task")
def train_stacking_meta_task() -> dict[str, Any]:
    """Train forecast stacking meta-model and register in MLflow."""
    try:
        return _run_async(_async_train_stacking_meta())
    except Exception as exc:
        logger.exception("Stacking meta training failed", error=str(exc))
        return {"status": "failed", "reason": str(exc)}


async def _async_train_stacking_meta() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.forecast.mlflow_registry import register_ensemble_run
    from app.services.forecast.stacking import (
        reset_stacking_meta_model,
        train_stacking_meta_from_prices,
    )
    from app.services.market_data.bars import get_bars_for_chart

    symbols = ["AAPL", "MSFT", "SPY", "BTC-USD"]
    all_prices: list[float] = []
    per_symbol: dict[str, dict[str, Any]] = {}

    async with AsyncSessionLocal() as session:
        for symbol in symbols:
            bars = await get_bars_for_chart(session, symbol, "1d", 400, force_refresh=False)
            closes = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
            per_symbol[symbol] = {"bars": len(closes)}
            if len(closes) >= 80:
                all_prices.extend(closes)

    if len(all_prices) < 120:
        return {"status": "failed", "reason": "insufficient_price_history", "per_symbol": per_symbol}

    trained = train_stacking_meta_from_prices(all_prices, method="lightgbm", horizon=5)
    if not trained.get("ok"):
        return {"status": "failed", "trained": trained, "per_symbol": per_symbol}

    reset_stacking_meta_model()
    acc = float(trained.get("train_accuracy") or 0.0)
    n = int(trained.get("n") or 0)
    registered = register_ensemble_run(
        model_name="forecast_stacking_meta",
        accuracy=acc,
        n=n,
        params={"method": "lightgbm", "members": "6", "horizon": "5"},
        tags={"stage": "stacking_meta", "live": "true"},
        promote_live=False,
        artifact_dict={"per_symbol": per_symbol, "path": trained.get("path")},
    )
    return {
        "status": "success",
        "trained": trained,
        "registered": registered,
        "per_symbol": per_symbol,
    }


@celery_app.task(name="app.tasks.forecast.register_chronos_member_task")
def register_chronos_member_task() -> dict[str, Any]:
    """Probe Chronos availability and register member status in MLflow."""
    try:
        return _run_async(_async_register_chronos_member())
    except Exception as exc:
        logger.exception("Chronos registration failed", error=str(exc))
        return {"status": "failed", "reason": str(exc)}


async def _async_register_chronos_member() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.forecast.chronos_component import get_chronos_component
    from app.services.forecast.mlflow_registry import register_ensemble_run
    from app.services.market_data.bars import get_bars_for_chart

    async with AsyncSessionLocal() as session:
        bars = await get_bars_for_chart(session, "SPY", "1d", 200, force_refresh=False)
        closes = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
    if len(closes) < 80:
        return {"status": "ok", "reason": "нет данных", "chronos_live": False, "registered": False}
    prices = closes
    chronos = get_chronos_component()
    note = "chronos_unavailable_momentum"
    acc = 0.5
    n = 0
    pred = chronos.predict(prices, horizon=10)
    note = pred.note
    if pred.note == "chronos_t5_tiny":
        acc = float(chronos.rolling_accuracy(list(prices), horizon=5))
        n = max(20, len(prices) // 10)
    live = note == "chronos_t5_tiny"
    registered = register_ensemble_run(
        model_name="chronos_t5_tiny",
        accuracy=acc,
        n=n,
        params={"member": "chronos", "note": note},
        tags={"stage": "ensemble_member", "chronos_live": "true" if live else "false"},
        promote_live=False,
        artifact_dict={"note": note, "available": pred.available, "chronos_live": live},
    )
    return {"status": "success", "note": note, "chronos_live": live, "registered": registered}


@celery_app.task(
    name="app.tasks.forecast.backfill_forecast_snapshots_task",
    soft_time_limit=7200,
    time_limit=7500,
)
def backfill_forecast_snapshots_task(
    symbols: list[str] | None = None,
    target_n: int = 100,
    batch_size: int = 10,
    max_iterations: int = 40,
) -> dict[str, Any]:
    """Historical snapshot backfill until scored direction accuracy n >= target."""
    try:
        return _run_async(
            _async_backfill_forecast_snapshots(
                symbols or ["AAPL", "MSFT", "SPY", "BTC-USD"],
                target_n=target_n,
                batch_size=batch_size,
                max_iterations=max_iterations,
            )
        )
    except Exception as exc:
        logger.exception("Forecast snapshot backfill failed", error=str(exc))
        return {"status": "failed", "reason": str(exc)}


async def _async_backfill_forecast_snapshots(
    symbols: list[str],
    *,
    target_n: int,
    batch_size: int,
    max_iterations: int,
) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.forecast.snapshot_backfill import backfill_until_target

    sym_tuple = tuple(s.strip().upper() for s in symbols if s.strip())
    async with AsyncSessionLocal() as session:
        result = await backfill_until_target(
            session,
            symbols=sym_tuple,
            target_n=target_n,
            batch_size=batch_size,
            max_iterations=max_iterations,
        )
    return {"status": "success", **result}


@celery_app.task(name="app.tasks.forecast.evaluate_ml_components_task")
def evaluate_ml_components_task(symbols: list[str] | None = None) -> dict[str, Any]:
    """Per-component before/after accuracy report with Wilson CIs."""
    try:
        return _run_async(_async_evaluate_ml_components(symbols or ["AAPL", "MSFT", "SPY", "BTC-USD"]))
    except Exception as exc:
        logger.exception("ML component evaluation failed", error=str(exc))
        return {"status": "failed", "reason": str(exc)}


async def _async_evaluate_ml_components(symbols: list[str]) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.forecast.component_evaluation import evaluate_component_accuracies
    from app.services.forecast.lob_features import lob_features_from_snapshot
    from app.services.forecast.shap_diagnostics import run_forecast_shap_diagnostics
    from app.services.market_data.bars import get_bars_for_chart
    from app.services.news.sentiment_aggregate import fetch_finbert_sentiment_map
    from app.services.orders.order_book import fetch_order_book

    report: dict[str, Any] = {"symbols": {}}
    async with AsyncSessionLocal() as session:
        for symbol in symbols:
            sym = symbol.strip().upper()
            bars = await get_bars_for_chart(session, sym, "1d", 504, force_refresh=False)
            closes = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
            if len(closes) < 80:
                report["symbols"][sym] = {"status": "skipped", "reason": "insufficient_bars"}
                continue
            sentiment_map = await fetch_finbert_sentiment_map(session, [sym])
            news_sentiment = float(sentiment_map.get(sym, 0.0))
            order_book_imbalance = 0.0
            lob_spread_bps = 0.0
            try:
                book = await fetch_order_book(sym)
                lob = lob_features_from_snapshot(book)
                order_book_imbalance = float(lob.order_flow_imbalance)
                lob_spread_bps = float(lob.bid_ask_spread_bps)
            except Exception:
                raise
            components = evaluate_component_accuracies(
                closes,
                symbol=sym,
                news_sentiment=news_sentiment,
                order_book_imbalance=order_book_imbalance,
            )
            enrichments = [
                {"news_sentiment": news_sentiment, "order_book_imbalance": order_book_imbalance}
                for _ in closes
            ]
            shap = run_forecast_shap_diagnostics(closes, symbol=sym, enrichments=enrichments)
            report["symbols"][sym] = {
                "components": [r.to_dict() for r in components],
                "shap": shap.to_dict(),
                "lob_spread_bps": lob_spread_bps,
                "news_sentiment": news_sentiment,
            }
    return {"status": "success", **report}


@celery_app.task(name="app.tasks.forecast.realize_daily_book_task")
def realize_daily_book_task() -> dict[str, Any]:
    """Mark yesterday's paper book vs stored daily bars. No vendor HTTP."""
    try:
        return _run_async(_async_realize_daily_book())
    except Exception as exc:
        logger.exception("Daily book realize failed", error=str(exc))
        return {"status": "failed", "reason": str(exc)}


async def _async_realize_daily_book() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.forecast.daily_book import (
        load_book,
        persist_realized,
        realize_book,
    )
    from app.services.forecast.excess_labels import benchmark_symbol_for
    from app.services.forecast.purged_cv import deflated_sharpe_ratio
    from app.services.market_data.bars import get_bars_for_chart

    book = load_book()
    if not book or not book.get("holdings"):
        return {"status": "empty", "reason": "no_book"}

    asset_returns: dict[str, float] = {}
    bench_ret = 0.0
    async with AsyncSessionLocal() as session:
        for h in book["holdings"]:
            sym = str(h.get("symbol") or "").upper()
            bars = await get_bars_for_chart(session, sym, "1d", 5, force_refresh=False)
            closes = [float(b.close) for b in bars if getattr(b, "close", None)]
            if len(closes) >= 2 and closes[-2] > 0:
                asset_returns[sym] = closes[-1] / closes[-2] - 1.0
        bench_sym = "SPY"
        if book["holdings"]:
            bench_sym = benchmark_symbol_for(str(book["holdings"][0].get("symbol") or "SPY"))
        bbars = await get_bars_for_chart(session, bench_sym, "1d", 5, force_refresh=False)
        bcloses = [float(b.close) for b in bbars if getattr(b, "close", None)]
        if len(bcloses) >= 2 and bcloses[-2] > 0:
            bench_ret = bcloses[-1] / bcloses[-2] - 1.0

    realized = realize_book(book, asset_returns, bench_ret)
    from app.services.forecast.daily_book import excess_history

    realized["deflated_sharpe"] = deflated_sharpe_ratio(
        excess_history() + ([float(realized["excess"])] if realized.get("excess") is not None else []),
        n_trials=max(int(book.get("count") or 1), 1),
    )
    persist_realized(realized)
    from app.services.forecast.calibration import load_ece
    from app.services.forecast.tear_sheet import book_turnover, load_previous_book, write_tear_sheet

    sheet = {
        "as_of": realized.get("as_of"),
        "excess": realized.get("excess"),
        "book_return": realized.get("book_return"),
        "deflated_sharpe": realized.get("deflated_sharpe"),
        "ece": load_ece(),
        "turnover": book_turnover(load_previous_book(str(realized.get("as_of") or "")), book),
        "scheme": realized.get("scheme"),
        "count": realized.get("count"),
        "note_ru": "Бумажный tear-sheet. Не live P&L.",
    }
    write_tear_sheet(sheet)
    try:
        from app.services.platform_desk.nightly import run_nightly_platform

        run_nightly_platform(book=book, realized=realized, asset_returns=asset_returns)
    except Exception:
        raise
    ece = sheet.get("ece") or {}
    if (
        float(ece.get("n") or 0) >= 40
        and not ece.get("reliable", True)
    ):
        try:
            from app.core.config import settings
            from app.services.alerts.telegram import send_telegram_message

            if settings.telegram_configured:
                await send_telegram_message(
                    settings.TELEGRAM_CHAT_ID,
                    f"Forecast ECE сломан: {ece}. Скор принудительно 5. Не C-данные.",
                )
        except Exception:
            raise
    return {"status": "ok" if realized.get("realized") else "incomplete", "book": realized}
