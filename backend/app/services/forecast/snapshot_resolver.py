"""Resolve forecast snapshots against realized OHLCV when horizon elapses."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import ForecastSnapshot, ForecastSnapshotResolution
from app.services.forecast.direction_accuracy import direction_from_return, is_scored_resolution
from app.services.market_data.bars import get_bars_for_chart
from app.utils.helpers import new_uuid, utcnow

logger = get_logger(__name__)

DEFAULT_RESOLVE_HORIZON_DAYS = 10


@dataclass(frozen=True, slots=True)
class SnapshotResolveResult:
    snapshot_id: str
    symbol: str
    horizon_days: int
    predicted_direction: int
    realized_return: float
    direction_hit: bool


def _log_aci_coverage(snapshot_symbol: str, aci_update: dict[str, object]) -> None:
    """Log ACI update without crashing resolve.

    ``record_conformal_coverage_from_resolution`` already includes ``symbol`` in
    the dict; passing ``symbol=`` again raises TypeError in structlog and used
    to abort the entire resolve batch (zero rows committed).
    """
    try:
        extra = {k: v for k, v in aci_update.items() if k != "symbol"}
        logger.debug(
            "aci_coverage_updated",
            snapshot_symbol=snapshot_symbol,
            **extra,
        )
    except Exception as exc:
        logger.warning(
            "aci_coverage_log_failed",
            snapshot_symbol=snapshot_symbol,
            error=str(exc)[:300],
        )


def _extract_prediction(snapshot: ForecastSnapshot) -> tuple[int, int]:
    payload = snapshot.payload or {}
    direction = payload.get("predicted_direction")
    if direction is None:
        hierarchy = payload.get("hierarchy_output") or {}
        point = hierarchy.get("point_forecast") or {}
        direction = point.get("expected_return_sign", 0)
    horizon = payload.get("horizon_days")
    if horizon is None:
        hierarchy = payload.get("hierarchy_output") or {}
        interval = hierarchy.get("interval_forecast") or {}
        horizon = interval.get("horizon_days", DEFAULT_RESOLVE_HORIZON_DAYS)
    return int(direction or 0), int(horizon or DEFAULT_RESOLVE_HORIZON_DAYS)


def _bars_needed_for_snapshot(snapshot_date: datetime, horizon_days: int, *, now: datetime | None = None) -> int:
    """How many recent daily bars to load so snapshot_date is inside the window.

    ``get_bars_for_chart`` returns the newest N bars only. Backfill snapshots can be
    months/years old, so a fixed ``horizon_days + 5`` window never contains them and
    resolution silently skips (clogging ASC-ordered batches with unresolved oldest rows).
    """
    ref = now or utcnow()
    snap = snapshot_date
    if snap.tzinfo is None:
        snap = snap.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    days_since = max(0, (ref.date() - snap.date()).days)
    # calendar gap + horizon + weekend/holiday slack
    return max(horizon_days + 5, days_since + horizon_days + 10)


async def _realized_return(
    db: AsyncSession,
    *,
    symbol: str,
    snapshot_date: datetime,
    horizon_days: int,
) -> float | None:
    bars_needed = _bars_needed_for_snapshot(snapshot_date, horizon_days)
    bars = await get_bars_for_chart(db, symbol, "1d", bars_needed, force_refresh=False)
    if not bars:
        return None
    snap_day = snapshot_date.date()
    idx = None
    for i, bar in enumerate(bars):
        bar_day = bar.timestamp.date() if hasattr(bar.timestamp, "date") else None
        if bar_day and bar_day <= snap_day:
            idx = i
    if idx is None or idx + horizon_days >= len(bars):
        return None
    start = float(bars[idx].close)
    end = float(bars[idx + horizon_days].close)
    if start <= 0:
        return None
    return (end - start) / start


async def resolve_mature_snapshots(
    db: AsyncSession,
    *,
    limit: int = 200,
) -> list[SnapshotResolveResult]:
    """Append resolution rows for snapshots whose horizon has passed."""
    now = utcnow()
    resolved_ids = select(ForecastSnapshotResolution.snapshot_id).scalar_subquery()
    stmt = (
        select(ForecastSnapshot)
        .where(ForecastSnapshot.id.not_in(resolved_ids))
        .order_by(ForecastSnapshot.snapshot_date.asc())
        .limit(limit)
    )
    snapshots = (await db.execute(stmt)).scalars().all()
    results: list[SnapshotResolveResult] = []
    track_payloads: list[dict] = []

    for snap in snapshots:
        try:
            predicted_dir, horizon = _extract_prediction(snap)
            mature_at = snap.snapshot_date + timedelta(days=horizon)
            if mature_at > now:
                continue
            realized = await _realized_return(
                db,
                symbol=snap.symbol,
                snapshot_date=snap.snapshot_date,
                horizon_days=horizon,
            )
            if realized is None:
                continue
            actual_dir = direction_from_return(realized)
            hit = (
                predicted_dir == actual_dir
                if is_scored_resolution(predicted_dir, realized)
                else False
            )

            conformal_payload = (snap.payload or {}).get("conformal_intervals")
            if isinstance(conformal_payload, dict):
                from app.services.forecast.adaptive_conformal import record_conformal_coverage_from_resolution

                aci_update = record_conformal_coverage_from_resolution(
                    snap.symbol,
                    realized,
                    conformal_payload,
                )
                if aci_update.get("updated"):
                    _log_aci_coverage(snap.symbol, aci_update)

            try:
                from sqlalchemy.orm.attributes import flag_modified

                from app.services.forecast.excess_labels import benchmark_symbol_for
                from app.services.forecast.excess_track import attach_excess_track_fields

                r20 = await _realized_return(
                    db, symbol=snap.symbol, snapshot_date=snap.snapshot_date, horizon_days=20
                )
                r60 = await _realized_return(
                    db, symbol=snap.symbol, snapshot_date=snap.snapshot_date, horizon_days=60
                )
                bench = benchmark_symbol_for(snap.symbol)
                b20 = await _realized_return(
                    db, symbol=bench, snapshot_date=snap.snapshot_date, horizon_days=20
                )
                b60 = await _realized_return(
                    db, symbol=bench, snapshot_date=snap.snapshot_date, horizon_days=60
                )
                payload = dict(snap.payload or {})
                attach_excess_track_fields(
                    payload,
                    asset_20=r20,
                    bench_20=b20,
                    asset_60=r60,
                    bench_60=b60,
                )
                snap.payload = payload
                flag_modified(snap, "payload")
                track_payloads.append(payload)
            except Exception as exc:
                logger.debug("excess_track attach skipped", symbol=snap.symbol, error=str(exc)[:200])

            row = ForecastSnapshotResolution(
                id=new_uuid(),
                snapshot_id=snap.id,
                symbol=snap.symbol.upper(),
                snapshot_date=snap.snapshot_date,
                horizon_days=horizon,
                predicted_direction=predicted_dir,
                realized_return=round(realized, 6),
                direction_hit=hit,
                resolved_at=now,
            )
            db.add(row)
            results.append(
                SnapshotResolveResult(
                    snapshot_id=snap.id,
                    symbol=snap.symbol,
                    horizon_days=horizon,
                    predicted_direction=predicted_dir,
                    realized_return=realized,
                    direction_hit=hit,
                )
            )
        except Exception as exc:
            logger.error(
                "snapshot_resolve_failed",
                symbol=getattr(snap, "symbol", None),
                snapshot_id=getattr(snap, "id", None),
                error=f"{type(exc).__name__}: {exc}"[:500],
            )
            continue

    if track_payloads:
        try:
            from app.services.forecast.calibration import ece_from_track_payloads

            ece_from_track_payloads(track_payloads)
        except Exception as exc:
            logger.debug("ece persist skipped", error=str(exc)[:160])

    if results:
        await db.commit()
    return results
