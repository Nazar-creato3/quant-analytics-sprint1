"""Assemble TickerAnalysisPayload for forecast API and chat (spec Section 7.1)."""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.market_data import SectorMappingORM
from app.schemas.ticker_analysis import PeerComparison, TickerAnalysisPayload
from app.services.factor.engine import FactorEngine
from app.services.market_analysis.covariance import (
    estimate_idiosyncratic_variance,
    factor_covariance_from_returns,
    factor_implied_variance,
)
from app.services.market_analysis.risk_metrics import compute_risk_metrics_from_prices
from app.services.market_analysis.scenarios import run_stress_scenarios
from app.services.market_analysis.shap_explainer import (
    compute_shap_top_factors,
    features_from_prices_volumes,
)
from app.services.market_analysis.style_factors import (
    STYLE_FACTOR_NAMES,
    RawStyleSignals,
    compute_raw_style_signals,
    compute_style_factor_exposures,
    merge_regression_betas,
)
from app.services.market_data.enrichment import fetch_fundamentals
from app.services.market_data.series_loader import load_forecast_price_series
from app.services.prediction_hierarchy.types import ForecastOutput

logger = get_logger(__name__)

_BENCHMARK_SYMBOL = "SPY"
_MIN_BARS = 60


async def _load_benchmark_prices(db: AsyncSession, *, limit: int = 260) -> list[float]:
    try:
        from app.services.instrument.resolver import resolve_or_create_instrument

        bench = await resolve_or_create_instrument(db, _BENCHMARK_SYMBOL)
        prices, _, _ = await load_forecast_price_series(
            db,
            bench.id,
            _BENCHMARK_SYMBOL,
            limit=limit,
            min_bars=10,
            persist=False,
        )
        return prices
    except Exception as exc:
        logger.debug("Benchmark load failed", error=str(exc))
        return []


async def _load_regression_exposures(
    db: AsyncSession,
    instrument_id: int,
) -> dict[str, float]:
    try:
        from app.utils.helpers import utcnow

        rows = await FactorEngine().estimate_for_instrument(
            db,
            instrument_id=instrument_id,
            as_of=utcnow(),
        )
        if not rows:
            return {}
        latest_time = max(row.time for row in rows)
        return {
            row.factor_name.value: round(float(row.beta), 4)
            for row in rows
            if row.time == latest_time
        }
    except Exception as exc:
        logger.debug("FactorEngine load failed", instrument_id=instrument_id, error=str(exc))
        return {}


async def _load_sector_peers(
    db: AsyncSession,
    instrument_id: int,
) -> tuple[str | None, list[int]]:
    sector_row = await db.get(SectorMappingORM, instrument_id)
    if sector_row is None:
        return None, []
    stmt = select(SectorMappingORM.instrument_id).where(
        SectorMappingORM.sector == sector_row.sector,
        SectorMappingORM.instrument_id != instrument_id,
    )
    peer_ids = [row[0] for row in (await db.execute(stmt)).all()]
    return sector_row.sector, peer_ids[:12]


async def _peer_raw_signals(
    db: AsyncSession,
    peer_ids: list[int],
    *,
    symbol_by_id: dict[int, str] | None = None,
) -> list[RawStyleSignals]:
    signals: list[RawStyleSignals] = []
    for peer_id in peer_ids:
        symbol = (symbol_by_id or {}).get(peer_id)
        if not symbol:
            continue
        try:
            prices, volumes, _ = await load_forecast_price_series(
                db,
                peer_id,
                symbol,
                limit=280,
                min_bars=20,
                persist=False,
            )
            fund = await fetch_fundamentals(symbol)
            signals.append(
                compute_raw_style_signals(
                    prices=prices,
                    volumes=volumes,
                    fundamentals=_normalize_fundamentals(fund),
                )
            )
        except Exception:
            continue
    return signals


def _normalize_fundamentals(raw: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key in (
        "market_cap",
        "pe_ratio",
        "roe",
        "averageVolume",
        "eps",
        "revenue_growth",
        "earnings_growth",
    ):
        value = raw.get(key)
        if value is not None:
            try:
                out[key if key != "averageVolume" else "average_volume"] = float(value)
            except (TypeError, ValueError):
                out[key if key != "averageVolume" else "average_volume"] = None
    return out


def _build_factor_return_proxies(
    prices: list[float],
    benchmark_prices: list[float],
) -> dict[str, list[float]]:
    """Proxy factor return series from price/benchmark history for F estimation."""
    from app.services.market_analysis.risk_metrics import returns_from_prices

    asset_r = returns_from_prices(prices)
    bench_r = returns_from_prices(benchmark_prices) if benchmark_prices else []
    length = min(len(asset_r), len(bench_r)) if bench_r else len(asset_r)
    if length < 5:
        return {}

    asset_r = asset_r[-length:]
    bench_r = bench_r[-length:] if bench_r else [0.0] * length

    mom: list[float] = [0.0] * length
    for idx in range(21, length):
        mom[idx] = sum(bench_r[idx - 21 : idx])

    vol: list[float] = [0.0] * length
    for idx in range(20, length):
        window = bench_r[idx - 20 : idx]
        mean = sum(window) / len(window)
        vol[idx] = math.sqrt(sum((v - mean) ** 2 for v in window) / max(1, len(window) - 1))

    return {
        "value": [-v for v in bench_r],
        "momentum": mom,
        "size": bench_r,
        "quality": bench_r,
        "low_vol": [-v for v in vol],
        "growth": bench_r,
        "liquidity": [abs(v) for v in bench_r],
    }


async def _peer_comparison(
    db: AsyncSession,
    *,
    sector: str | None,
    peer_ids: list[int],
    target_score: float | None,
) -> PeerComparison:
    if not sector:
        return PeerComparison(sector_avg_score=None, sector=None, peer_count=0)

    scores: list[float] = []
    try:
        from app.services.forecast.snapshot_repository import latest_snapshots_for_symbols
        from app.services.instrument.resolver import resolve_or_create_instrument

        symbols: list[str] = []
        for peer_id in peer_ids[:8]:
            try:
                from sqlalchemy import select as sa_select
                from app.domain.instrument import InstrumentORM

                row = await db.get(InstrumentORM, peer_id)
                if row:
                    symbols.append(row.symbol)
            except Exception:
                continue

        if symbols:
            snaps = await latest_snapshots_for_symbols(db, symbols)
            for snap in snaps:
                conf = float((snap.payload or {}).get("confidence", 0.0))
                if conf > 0:
                    scores.append(conf)
    except Exception as exc:
        logger.debug("Peer score load failed", error=str(exc))

    sector_avg = round(sum(scores) / len(scores), 4) if scores else None
    return PeerComparison(
        sector_avg_score=sector_avg,
        sector=sector,
        peer_count=len(peer_ids),
    )


async def build_ticker_analysis_payload(
    symbol: str,
    db: AsyncSession,
    *,
    instrument_id: int | None = None,
    hierarchy: ForecastOutput | None = None,
) -> TickerAnalysisPayload:
    """Build structured analysis object with explicit nulls for missing data."""
    normalized = symbol.strip().upper()
    gaps: list[str] = []

    if instrument_id is None:
        from app.services.instrument.resolver import resolve_or_create_instrument

        instrument = await resolve_or_create_instrument(db, normalized)
        instrument_id = instrument.id

    prices, volumes, source = await load_forecast_price_series(
        db,
        instrument_id,
        normalized,
        limit=280,
        min_bars=10,
    )
    if len(prices) < _MIN_BARS:
        gaps.append(f"market_ohlcv.{normalized} (need ≥{_MIN_BARS} bars, have {len(prices)})")

    fundamentals_raw = await fetch_fundamentals(normalized)
    fundamentals = _normalize_fundamentals(fundamentals_raw)
    if not fundamentals.get("market_cap") and not fundamentals.get("pe_ratio"):
        gaps.append(f"fundamentals.{normalized} (FMP/yfinance — market_cap, P/E for Value/Size/Quality)")

    sector, peer_ids = await _load_sector_peers(db, instrument_id)
    target_signals = compute_raw_style_signals(
        prices=prices,
        volumes=volumes,
        fundamentals=fundamentals,
    )
    peer_signals = await _peer_raw_signals(db, peer_ids) if peer_ids else []
    style_z = compute_style_factor_exposures(
        target_signals=target_signals,
        peer_signals=peer_signals or None,
        prices=prices if not peer_signals else None,
    )

    regression_betas = await _load_regression_exposures(db, instrument_id)
    if not regression_betas:
        gaps.append(f"factor_regression.{normalized} (FactorEngine — need sector universe in DB)")

    exposures: dict[str, float | None] = merge_regression_betas(style_z, regression_betas)
    for reg_name, reg_val in regression_betas.items():
        if reg_name not in exposures and reg_name not in STYLE_FACTOR_NAMES:
            exposures[reg_name] = reg_val

    benchmark_prices = await _load_benchmark_prices(db)
    if not benchmark_prices:
        gaps.append(f"benchmark.{_BENCHMARK_SYMBOL} (beta/tracking error need benchmark OHLCV)")

    risk = compute_risk_metrics_from_prices(prices, benchmark_prices=benchmark_prices or None)
    risk_dict = risk.as_dict()
    if risk_dict["var_95"] is None:
        gaps.append(f"risk_metrics.{normalized} (insufficient return history)")

    scenario_exposures = dict(exposures)
    scenario_exposures.update(regression_betas)
    scenario_results = run_stress_scenarios(scenario_exposures)

    factor_implied: dict[str, Any] | None = None
    if len(prices) >= _MIN_BARS and benchmark_prices:
        from app.services.market_analysis.risk_metrics import returns_from_prices

        asset_returns = returns_from_prices(prices)
        factor_returns = _build_factor_return_proxies(prices, benchmark_prices)
        if factor_returns:
            f_cov, f_order = factor_covariance_from_returns(factor_returns)
            if f_order:
                eps_var = estimate_idiosyncratic_variance(
                    asset_returns,
                    factor_returns,
                    exposures,
                    factor_order=f_order,
                )
                factor_implied = factor_implied_variance(
                    exposures,
                    f_cov,
                    factor_order=f_order,
                    idiosyncratic_variance=eps_var,
                )

    ml_score: float | None = None
    if hierarchy is not None:
        ml_score = round(float(hierarchy.calibrated_confidence), 4)
    else:
        try:
            from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator

            output = await get_hierarchy_orchestrator().get_forecast(
                db,
                instrument_id,
                symbol=normalized,
                include_narrative=False,
                use_cache=True,
            )
            ml_score = round(float(output.calibrated_confidence), 4)
            hierarchy = output
        except Exception as exc:
            logger.debug("ML score load failed", symbol=normalized, error=str(exc))
            gaps.append(f"ml_score.{normalized} ({exc})")

    shap_features = features_from_prices_volumes(prices, volumes) if prices else {}
    shap_factors, shap_ok, shap_gaps = compute_shap_top_factors(shap_features)
    gaps.extend(shap_gaps)

    peer = await _peer_comparison(
        db,
        sector=sector,
        peer_ids=peer_ids,
        target_score=ml_score,
    )

    if source:
        gaps.append(f"market_ohlcv.{normalized} (partial — enriched via {source})")

    return TickerAnalysisPayload(
        ticker=normalized,
        ml_score=ml_score,
        shap_top_factors=shap_factors,
        factor_exposures=exposures,
        risk_metrics=risk_dict,
        scenario_results=scenario_results,
        peer_comparison=peer,
        factor_implied_covariance=factor_implied,
        data_gaps=gaps,
        shap_available=shap_ok,
    )


async def build_ticker_analysis_payload_by_symbol(
    symbol: str,
    db: AsyncSession,
    **kwargs: Any,
) -> TickerAnalysisPayload:
    """Alias matching spec naming (`symbol, db`)."""
    return await build_ticker_analysis_payload(symbol, db, **kwargs)
