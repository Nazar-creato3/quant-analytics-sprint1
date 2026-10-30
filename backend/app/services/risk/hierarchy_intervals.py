"""Load prediction-hierarchy interval bands for profit projection (maneuvers + enrichment)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.prediction_hierarchy.cache import get_cached_forecast
from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator
from app.services.prediction_hierarchy.types import IntervalForecast
from app.services.risk.profit_projection import IntervalForecastLike, parse_interval_from_cache

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _IntervalAdapter:
    horizon_days: int
    p10: float
    p90: float
    rolling_volatility: float
    confidence_multiplier: float = 1.645


def interval_from_forecast(interval: IntervalForecast | None) -> IntervalForecastLike | None:
    if interval is None:
        return None
    if interval.rolling_volatility <= 0 and interval.p10 == interval.p90 == 0:
        return None
    return _IntervalAdapter(
        horizon_days=int(interval.horizon_days),
        p10=float(interval.p10),
        p90=float(interval.p90),
        rolling_volatility=float(interval.rolling_volatility),
        confidence_multiplier=float(interval.confidence_multiplier),
    )


async def load_interval_for_instrument(
    db: AsyncSession,
    *,
    instrument_id: int,
    symbol: str,
    use_orchestrator: bool = True,
) -> IntervalForecastLike | None:
    """Resolve hierarchy interval: Redis cache first, optional live orchestrator."""
    cached = await get_cached_forecast(instrument_id)
    if cached:
        parsed = parse_interval_from_cache(cached)
        if parsed is not None:
            return parsed

    if not use_orchestrator:
        return None

    try:
        orchestrator = get_hierarchy_orchestrator()
        output = await orchestrator.get_forecast(
            db,
            instrument_id,
            symbol=symbol,
            include_narrative=False,
            use_cache=True,
        )
        return interval_from_forecast(output.interval_forecast)
    except Exception as exc:
        logger.debug(
            "Hierarchy interval unavailable",
            symbol=symbol,
            instrument_id=instrument_id,
            error=str(exc),
        )
        return None


async def load_intervals_for_tickers(
    db: AsyncSession,
    tickers: list[str],
    *,
    use_orchestrator: bool = True,
) -> dict[str, IntervalForecastLike | None]:
    """Batch load intervals keyed by upper-case ticker."""
    intervals, _hints = await load_intervals_and_hints_for_tickers(
        db, tickers, use_orchestrator=use_orchestrator
    )
    return intervals


async def load_intervals_and_hints_for_tickers(
    db: AsyncSession,
    tickers: list[str],
    *,
    use_orchestrator: bool = True,
) -> tuple[dict[str, IntervalForecastLike | None], dict[str, Any]]:
    """Intervals + hierarchy hints from the same Redis payload (one get per ticker)."""
    from app.services.instrument.resolver import resolve_or_create_instrument
    from app.services.risk.hierarchy_hints import hint_from_cached_forecast

    out: dict[str, IntervalForecastLike | None] = {}
    hints: dict[str, Any] = {}
    seen: set[str] = set()
    for raw in tickers:
        sym = raw.strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        try:
            inst = await resolve_or_create_instrument(db, sym)
            cached = await get_cached_forecast(inst.id)
            hints[sym] = hint_from_cached_forecast(sym, cached)
            parsed = parse_interval_from_cache(cached) if cached else None
            if parsed is not None:
                out[sym] = parsed
            else:
                out[sym] = await load_interval_for_instrument(
                    db,
                    instrument_id=inst.id,
                    symbol=inst.symbol,
                    use_orchestrator=use_orchestrator,
                )
        except Exception as exc:
            logger.warning("Interval load failed for ticker", ticker=sym, error=str(exc))
            out[sym] = None
    return out, hints


async def warm_missing_hierarchy_hints(
    db: AsyncSession,
    tickers: list[str],
    hints: dict[str, Any],
    intervals: dict[str, IntervalForecastLike | None],
    *,
    max_warm: int = 8,
) -> tuple[dict[str, Any], dict[str, IntervalForecastLike | None]]:
    """Fill empty hierarchy cache for analysis names so first-click is not blind."""
    from app.services.instrument.resolver import resolve_or_create_instrument
    from app.services.risk.hierarchy_hints import hint_from_cached_forecast

    warmed = 0
    for raw in tickers:
        if warmed >= max_warm:
            break
        sym = raw.strip().upper()
        hint = hints.get(sym)
        if hint is not None and getattr(hint, "cache_hit", False):
            continue
        try:
            inst = await resolve_or_create_instrument(db, sym)
            parsed = await asyncio.wait_for(
                load_interval_for_instrument(
                    db,
                    instrument_id=inst.id,
                    symbol=inst.symbol,
                    use_orchestrator=True,
                ),
                timeout=12.0,
            )
            cached = await get_cached_forecast(inst.id)
            hints[sym] = hint_from_cached_forecast(sym, cached)
            if parsed is not None:
                intervals[sym] = parsed
            warmed += 1
        except (asyncio.TimeoutError, Exception) as exc:
            logger.debug("hierarchy_warm_failed", ticker=sym, error=str(exc)[:160])
            # A failed flush leaves the session in a rolled-back state; without this every
            # following ticker failed with "transaction has been rolled back".
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return hints, intervals
