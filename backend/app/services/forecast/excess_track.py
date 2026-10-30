"""Public track: did yesterday's beat-benchmark call match realized excess?"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ForecastSnapshot
from app.services.forecast.excess_labels import benchmark_symbol_for
from app.services.forecast.market_beat import probability_to_score_1_10
from app.services.forecast.snapshot_repository import SNAPSHOT_SOURCE_LIVE


def predicted_beat(p_beat: float | None) -> bool | None:
    if p_beat is None:
        return None
    return float(p_beat) >= 0.5


def excess_hit(*, predicted: bool | None, excess: float | None) -> bool | None:
    if predicted is None or excess is None:
        return None
    actual = excess > 0.0
    return predicted == actual


def summarize_excess_payloads(payloads: list[dict[str, Any]], *, horizon: int = 20) -> dict[str, Any]:
    key = f"hit_{horizon}"
    hits = 0
    n = 0
    for payload in payloads:
        track = (payload or {}).get("excess_track") or {}
        if track.get(key) is None:
            continue
        n += 1
        if track[key]:
            hits += 1
    acc = (hits / n) if n else None
    return {
        "accuracy": acc,
        "sample_size": n,
        "hits": hits,
        "horizon": horizon,
        "formatted_ru": (
            f"Обгон бенчмарка {horizon}д: {hits}/{n} ({acc:.0%})"
            if n and acc is not None
            else f"Обгон бенчмарка {horizon}д: мало исходов"
        ),
    }


async def rolling_excess_track(
    db: AsyncSession,
    *,
    symbol: str,
    horizon: int = 20,
    window_days: int = 90,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    stmt = (
        select(ForecastSnapshot)
        .where(
            ForecastSnapshot.symbol == symbol.upper(),
            ForecastSnapshot.source == SNAPSHOT_SOURCE_LIVE,
            ForecastSnapshot.snapshot_date >= cutoff,
        )
        .order_by(desc(ForecastSnapshot.snapshot_date))
        .limit(200)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return summarize_excess_payloads([r.payload or {} for r in rows], horizon=horizon)


def attach_excess_track_fields(
    payload: dict[str, Any],
    *,
    asset_20: float | None,
    bench_20: float | None,
    asset_60: float | None,
    bench_60: float | None,
) -> dict[str, Any]:
    beat = payload.get("market_beat") or {}
    p20 = beat.get("p_beat_20")
    p60 = beat.get("p_beat_60")
    ex20 = None if asset_20 is None or bench_20 is None else asset_20 - bench_20
    ex60 = None if asset_60 is None or bench_60 is None else asset_60 - bench_60
    payload["excess_track"] = {
        "benchmark": benchmark_symbol_for(str(beat.get("symbol") or payload.get("symbol") or "")),
        "asset_20": asset_20,
        "bench_20": bench_20,
        "excess_20": ex20,
        "pred_beat_20": predicted_beat(p20),
        "hit_20": excess_hit(predicted=predicted_beat(p20), excess=ex20),
        "score_said_20": probability_to_score_1_10(float(p20)) if p20 is not None else None,
        "asset_60": asset_60,
        "bench_60": bench_60,
        "excess_60": ex60,
        "pred_beat_60": predicted_beat(p60),
        "hit_60": excess_hit(predicted=predicted_beat(p60), excess=ex60),
        "score_said_60": probability_to_score_1_10(float(p60)) if p60 is not None else None,
    }
    return payload
