"""Shared predicted_direction extraction for live + backfill snapshots."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.forecast.ensemble import get_ensemble_forecast_engine
from app.services.forecast.lob_features import lob_features_from_snapshot
from app.services.forecast.symbol_horizon import horizon_for_symbol
from app.services.market_data.series_loader import load_forecast_price_series
from app.services.news.sentiment_aggregate import fetch_finbert_sentiment_map
from app.services.prediction_hierarchy.types import ForecastOutput


async def enrich_payload_predicted_direction(
    db: AsyncSession,
    *,
    instrument_id: int,
    symbol: str,
    hierarchy: ForecastOutput,
    payload: dict[str, Any],
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Attach ensemble + predicted_direction used by resolver / Wilson accuracy.

    Prefer ensemble ``direction_consensus`` (same directional field as the live
    forecast API). Fall back to hierarchy ``expected_return_sign``.

    Intentionally omits live-accuracy suppression so evaluation snapshots keep
    the raw directional call.
    """
    prices, _volumes, _source = await load_forecast_price_series(
        db,
        instrument_id,
        symbol,
        limit=120,
        as_of=as_of,
    )
    momentum_score = (
        hierarchy.point_forecast.momentum_score if hierarchy.point_forecast else None
    )
    horizon_days = horizon_for_symbol(prices, symbol=symbol)
    news_sentiment_map = await fetch_finbert_sentiment_map(db, [symbol], as_of=as_of)
    news_sentiment = float(news_sentiment_map.get(symbol.upper(), 0.0))

    order_book_imbalance = 0.0
    lob_spread_bps = 0.0
    try:
        from app.services.orders.order_book import fetch_order_book

        book = await fetch_order_book(symbol)
        lob = lob_features_from_snapshot(book)
        order_book_imbalance = float(lob.order_flow_imbalance)
        lob_spread_bps = float(lob.bid_ask_spread_bps)
    except Exception:
        pass

    ensemble = get_ensemble_forecast_engine().compute(
        prices,
        symbol=symbol,
        momentum_score=momentum_score,
        calibrated_confidence=float(hierarchy.calibrated_confidence or 0.5),
        horizon_days=horizon_days,
        news_sentiment=news_sentiment,
        order_book_imbalance=order_book_imbalance,
        lob_spread_bps=lob_spread_bps,
    )
    expected_return_sign = (
        int(hierarchy.point_forecast.expected_return_sign)
        if hierarchy.point_forecast
        else 0
    )
    direction = (
        int(ensemble.direction_consensus)
        if ensemble.direction_consensus != 0
        else expected_return_sign
    )
    payload["ensemble"] = ensemble.to_dict()
    payload["expected_return_sign"] = expected_return_sign
    payload["predicted_direction"] = int(direction)
    payload["horizon_days"] = horizon_days
    return payload
