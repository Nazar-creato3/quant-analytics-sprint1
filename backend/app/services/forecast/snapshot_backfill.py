"""Historical forecast snapshot backfill using the live pipeline (point-in-time)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Integer, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import ForecastSnapshot, ForecastSnapshotResolution
from app.services.forecast.daily_builder import get_daily_forecast_builder
from app.services.forecast.direction_accuracy import (
    DIRECTION_RETURN_THRESHOLD,
    scored_resolution_clause,
)
from app.services.forecast.snapshot_repository import (
    SNAPSHOT_SOURCE_BACKFILL,
    delete_snapshots_for_day,
    snapshot_exists_for_day,
    upsert_daily_snapshot,
)
from app.services.forecast.snapshot_resolver import resolve_mature_snapshots
from app.services.market_data.bars import get_bars_for_chart
from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator
from app.utils.wilson_ci import WilsonInterval, wilson_ci, wilson_ci_from_rate

logger = get_logger(__name__)

DEFAULT_BACKFILL_TICKERS = ("AAPL", "MSFT", "SPY", "BTC-USD")
MIN_HISTORY_BARS = 30
DEFAULT_MAX_HORIZON_DAYS = 10


@dataclass(frozen=True, slots=True)
class BackfillDayResult:
    symbol: str
    snapshot_date: datetime
    snapshot_id: str | None
    skipped: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class AccuracyReportRow:
    symbol: str
    horizon_days: int
    sample_size: int
    accuracy: float | None
    ci_low: float | None
    ci_high: float | None
    hits: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "horizon_days": self.horizon_days,
            "n": self.sample_size,
            "accuracy": self.accuracy,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "hits": self.hits,
        }


async def _trading_days_for_symbol(
    db: AsyncSession,
    symbol: str,
    *,
    years: float = 2.0,
    max_horizon_days: int = DEFAULT_MAX_HORIZON_DAYS,
) -> list[datetime]:
    """Return UTC timestamps for daily bars usable in backfill."""
    lookback_days = int(years * 366) + max_horizon_days + MIN_HISTORY_BARS + 5
    bars = await get_bars_for_chart(db, symbol, "1d", lookback_days, force_refresh=False)
    if len(bars) < MIN_HISTORY_BARS + max_horizon_days + 1:
        return []

    usable = bars[MIN_HISTORY_BARS - 1 : len(bars) - max_horizon_days]
    days: list[datetime] = []
    for bar in usable:
        ts = bar.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        days.append(ts)
    return days


async def generate_backfill_snapshot(
    db: AsyncSession,
    *,
    instrument_id: int,
    symbol: str,
    as_of: datetime,
    skip_existing: bool = True,
) -> BackfillDayResult:
    """Build one point-in-time snapshot via live orchestrator + daily builder."""
    sym = symbol.upper()
    if skip_existing and await snapshot_exists_for_day(
        db, symbol=sym, snapshot_date=as_of, source=SNAPSHOT_SOURCE_BACKFILL
    ):
        return BackfillDayResult(symbol=sym, snapshot_date=as_of, snapshot_id=None, skipped=True, reason="exists")
    if not skip_existing:
        await delete_snapshots_for_day(
            db, symbol=sym, snapshot_date=as_of, source=SNAPSHOT_SOURCE_BACKFILL
        )

    orchestrator = get_hierarchy_orchestrator()
    builder = get_daily_forecast_builder()
    try:
        hierarchy = await orchestrator.get_forecast(
            db,
            instrument_id,
            symbol=sym,
            include_narrative=False,
            use_cache=False,
            as_of=as_of,
        )
        payload = await builder.build(
            db,
            instrument_id=instrument_id,
            symbol=sym,
            as_of=as_of,
            skip_explain=True,
        )
    except Exception as exc:
        import traceback

        logger.warning(
            "Backfill snapshot failed",
            symbol=sym,
            as_of=as_of.isoformat(),
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        logger.warning("Backfill traceback", traceback=traceback.format_exc())
        return BackfillDayResult(
            symbol=sym,
            snapshot_date=as_of,
            snapshot_id=None,
            skipped=True,
            reason=f"{type(exc).__name__}: {exc}",
        )

    payload["hierarchy_output"] = hierarchy.to_dict()
    payload["calibrated_confidence"] = hierarchy.calibrated_confidence
    payload["action_recommendation"] = hierarchy.action_forecast.recommendation.value
    from app.services.forecast.snapshot_direction import enrich_payload_predicted_direction

    payload = await enrich_payload_predicted_direction(
        db,
        instrument_id=instrument_id,
        symbol=sym,
        hierarchy=hierarchy,
        payload=payload,
        as_of=as_of,
    )
    payload["horizon_days"] = (
        hierarchy.interval_forecast.horizon_days if hierarchy.interval_forecast else DEFAULT_MAX_HORIZON_DAYS
    )
    payload["backfill_as_of"] = as_of.isoformat()

    row = await upsert_daily_snapshot(
        db,
        instrument_id=instrument_id,
        symbol=sym,
        payload=payload,
        snapshot_date=as_of,
        source=SNAPSHOT_SOURCE_BACKFILL,
    )
    return BackfillDayResult(symbol=sym, snapshot_date=as_of, snapshot_id=row.id, skipped=False)


async def backfill_symbol(
    db: AsyncSession,
    *,
    instrument_id: int,
    symbol: str,
    years: float = 2.0,
    sample_every: int = 1,
    max_days: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Generate backfill snapshots for one symbol over historical trading days."""
    days = await _trading_days_for_symbol(db, symbol, years=years)
    if sample_every > 1:
        days = days[::sample_every]
    if max_days is not None:
        days = days[-max_days:]

    created = 0
    skipped = 0
    errors: list[str] = []
    for as_of in days:
        result = await generate_backfill_snapshot(
            db,
            instrument_id=instrument_id,
            symbol=symbol,
            as_of=as_of,
            skip_existing=not force,
        )
        if result.skipped:
            skipped += 1
            if result.reason and result.reason != "exists":
                errors.append(f"{as_of.date()}: {result.reason}")
        else:
            created += 1

    return {
        "symbol": symbol.upper(),
        "trading_days": len(days),
        "created": created,
        "skipped": skipped,
        "errors": errors[:20],
    }


async def resolve_all_backfill_snapshots(
    db: AsyncSession,
    *,
    batch_limit: int = 500,
    max_batches: int = 200,
) -> int:
    """Resolve mature backfill snapshots using the same resolver as live."""
    total = 0
    for _ in range(max_batches):
        batch = await resolve_mature_snapshots(db, limit=batch_limit)
        if not batch:
            break
        total += len(batch)
    return total


async def compute_resolution_accuracy_report(
    db: AsyncSession,
    *,
    symbols: tuple[str, ...] | None = None,
    sources: tuple[str, ...] | None = ("backfill", "live"),
) -> list[AccuracyReportRow]:
    """Aggregate direction_hit accuracy with Wilson 95% CI per symbol/horizon."""
    sym_filter = symbols or DEFAULT_BACKFILL_TICKERS
    upper_syms = [s.upper() for s in sym_filter]

    snapshot_ids = select(ForecastSnapshot.id).where(
        ForecastSnapshot.symbol.in_(upper_syms),
    )
    if sources:
        snapshot_ids = snapshot_ids.where(ForecastSnapshot.source.in_(sources))

    stmt = (
        select(
            ForecastSnapshotResolution.symbol,
            ForecastSnapshotResolution.horizon_days,
            func.count().label("n"),
            func.sum(cast(ForecastSnapshotResolution.direction_hit, Integer)).label("hits"),
            func.avg(cast(ForecastSnapshotResolution.direction_hit, Integer)).label("acc"),
        )
        .where(
            ForecastSnapshotResolution.snapshot_id.in_(snapshot_ids),
            scored_resolution_clause(),
        )
        .group_by(
            ForecastSnapshotResolution.symbol,
            ForecastSnapshotResolution.horizon_days,
        )
        .order_by(
            ForecastSnapshotResolution.symbol,
            ForecastSnapshotResolution.horizon_days,
        )
    )
    rows = (await db.execute(stmt)).all()
    report: list[AccuracyReportRow] = []
    for row in rows:
        n = int(row.n or 0)
        hits = int(row.hits or 0)
        acc = float(row.acc) if row.acc is not None and n > 0 else None
        interval: WilsonInterval | None = wilson_ci(hits, n) if n > 0 else None
        report.append(
            AccuracyReportRow(
                symbol=str(row.symbol),
                horizon_days=int(row.horizon_days),
                sample_size=n,
                accuracy=acc,
                ci_low=interval.ci_low if interval else None,
                ci_high=interval.ci_high if interval else None,
                hits=hits,
            )
        )
    return report


def report_to_markdown(rows: list[AccuracyReportRow], *, title: str = "Forecast Snapshot Accuracy") -> str:
    """Render accuracy summary as markdown."""
    lines = [f"# {title}", "", "| Symbol | Horizon | n | Accuracy | 95% Wilson CI |", "| --- | ---: | ---: | ---: | --- |"]
    for row in rows:
        if row.accuracy is None or row.sample_size == 0:
            acc_str = "—"
            ci_str = "—"
        else:
            acc_str = f"{row.accuracy * 100:.1f}%"
            if row.ci_low is not None and row.ci_high is not None:
                ci_str = f"{row.ci_low * 100:.0f}–{row.ci_high * 100:.0f}%"
            else:
                ci_str = "—"
        lines.append(
            f"| {row.symbol} | {row.horizon_days}d | {row.sample_size} | {acc_str} | {ci_str} |"
        )
    lines.append("")
    lines.append(
        "_Live ensemble suppression uses `source=live` only; this report includes configured sources._"
    )
    return "\n".join(lines)


def report_to_json(rows: list[AccuracyReportRow]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": [row.to_dict() for row in rows],
    }


async def scored_resolution_count(
    db: AsyncSession,
    symbol: str,
    *,
    sources: tuple[str, ...] | None = ("backfill", "live"),
) -> int:
    """Directional scored resolutions for one symbol (Wilson report denominator)."""
    rows = await compute_resolution_accuracy_report(db, symbols=(symbol,), sources=sources)
    return sum(r.sample_size for r in rows)


@dataclass(frozen=True, slots=True)
class UnfilteredResolutionCount:
    """Raw vs scored n from forecast_snapshot_resolutions with no horizon/source/window filter."""

    symbol: str
    raw_n: int
    scored_n: int
    hits: int

    @property
    def accuracy(self) -> float | None:
        if self.scored_n <= 0:
            return None
        return self.hits / self.scored_n


async def unfiltered_resolution_counts(
    db: AsyncSession,
    symbols: tuple[str, ...],
) -> dict[str, UnfilteredResolutionCount]:
    """Count resolutions per symbol from the raw table (health-check denominator).

    No source join, no rolling window, no horizon_for_symbol filter — those were
    dropping MSFT/SPY to n=0 while AAPL showed a handful of live rows.
    """
    upper = [s.upper() for s in symbols]
    stmt = (
        select(
            ForecastSnapshotResolution.symbol,
            func.count().label("raw_n"),
            func.sum(
                cast(
                    and_(
                        ForecastSnapshotResolution.predicted_direction != 0,
                        func.abs(ForecastSnapshotResolution.realized_return)
                        > DIRECTION_RETURN_THRESHOLD,
                    ),
                    Integer,
                )
            ).label("scored_n"),
            func.sum(
                cast(
                    and_(
                        ForecastSnapshotResolution.predicted_direction != 0,
                        func.abs(ForecastSnapshotResolution.realized_return)
                        > DIRECTION_RETURN_THRESHOLD,
                        ForecastSnapshotResolution.direction_hit.is_(True),
                    ),
                    Integer,
                )
            ).label("hits"),
        )
        .where(ForecastSnapshotResolution.symbol.in_(upper))
        .group_by(ForecastSnapshotResolution.symbol)
    )
    rows = (await db.execute(stmt)).all()
    out: dict[str, UnfilteredResolutionCount] = {
        s: UnfilteredResolutionCount(symbol=s, raw_n=0, scored_n=0, hits=0) for s in upper
    }
    for row in rows:
        sym = str(row.symbol).upper()
        out[sym] = UnfilteredResolutionCount(
            symbol=sym,
            raw_n=int(row.raw_n or 0),
            scored_n=int(row.scored_n or 0),
            hits=int(row.hits or 0),
        )
    return out


async def scored_resolutions_since(
    db: AsyncSession,
    symbols: tuple[str, ...],
    *,
    since: datetime,
) -> dict[str, int]:
    """Scored resolution rows with resolved_at >= since (growth / stall detector)."""
    upper = [s.upper() for s in symbols]
    stmt = (
        select(
            ForecastSnapshotResolution.symbol,
            func.count().label("n"),
        )
        .where(
            ForecastSnapshotResolution.symbol.in_(upper),
            ForecastSnapshotResolution.resolved_at >= since,
            scored_resolution_clause(),
        )
        .group_by(ForecastSnapshotResolution.symbol)
    )
    rows = (await db.execute(stmt)).all()
    out = {s: 0 for s in upper}
    for row in rows:
        out[str(row.symbol).upper()] = int(row.n or 0)
    return out


async def mature_unresolved_counts(
    db: AsyncSession,
    symbols: tuple[str, ...],
    *,
    horizon_days: int = DEFAULT_MAX_HORIZON_DAYS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Unresolved snapshots whose default horizon has elapsed."""
    upper = [s.upper() for s in symbols]
    ref = now or datetime.now(timezone.utc)
    cutoff = ref - timedelta(days=horizon_days)
    resolved_ids = select(ForecastSnapshotResolution.snapshot_id)
    stmt = (
        select(ForecastSnapshot.symbol, func.count().label("n"))
        .where(
            ForecastSnapshot.symbol.in_(upper),
            ForecastSnapshot.id.not_in(resolved_ids),
            ForecastSnapshot.snapshot_date <= cutoff,
        )
        .group_by(ForecastSnapshot.symbol)
    )
    rows = (await db.execute(stmt)).all()
    out = {s: 0 for s in upper}
    for row in rows:
        out[str(row[0]).upper()] = int(row[1] or 0)
    return out


def _finalize_backfill_summary(
    summary: dict[str, Any],
    *,
    target_n: int,
    counts: dict[str, int],
    failed: dict[str, str],
) -> dict[str, Any]:
    below_target = {sym: n for sym, n in counts.items() if n < target_n}
    succeeded = [sym for sym, n in counts.items() if n >= target_n and sym not in failed]
    summary["counts"] = counts
    summary["succeeded"] = succeeded
    summary["failed"] = failed
    summary["below_target"] = below_target
    if failed and (succeeded or below_target):
        summary["status"] = "partial_failure"
    elif failed and not succeeded:
        summary["status"] = "failed"
    elif below_target:
        summary["status"] = "incomplete"
    else:
        summary["status"] = "complete"
    if failed:
        logger.error(
            "backfill_symbol_failures",
            failed=failed,
            succeeded=succeeded,
            below_target=below_target,
        )
    logger.info(
        "backfill_until_target_summary",
        status=summary["status"],
        succeeded=succeeded,
        failed=list(failed.keys()),
        below_target=below_target,
        counts=counts,
    )
    return summary


async def backfill_until_target(
    db: AsyncSession,
    *,
    symbols: tuple[str, ...] = DEFAULT_BACKFILL_TICKERS,
    target_n: int = 100,
    batch_size: int = 10,
    max_iterations: int = 40,
) -> dict[str, Any]:
    """Backfill + resolve in batches until each symbol reaches target scored n."""
    from sqlalchemy import text

    summary: dict[str, Any] = {
        "target_n": target_n,
        "batch_size": batch_size,
        "iterations": 0,
        "symbols": {},
        "failed": {},
        "succeeded": [],
        "status": "incomplete",
    }
    instrument_ids: dict[str, int] = {}
    failed: dict[str, str] = {}
    for sym in symbols:
        upper = sym.upper()
        iid = (
            await db.execute(text("SELECT id FROM instruments WHERE symbol=:s LIMIT 1"), {"s": upper})
        ).scalar()
        if iid is None:
            failed[upper] = "no_instrument"
            summary["symbols"][upper] = {"error": "no_instrument", "n": 0}
            logger.error("backfill_symbol_failed", symbol=upper, error="no_instrument")
        else:
            instrument_ids[upper] = int(iid)

    counts_after: dict[str, int] = {}
    for iteration in range(max_iterations):
        summary["iterations"] = iteration + 1
        counts_before = {sym: await scored_resolution_count(db, sym) for sym in instrument_ids}
        if all(n >= target_n for n in counts_before.values()) and not failed:
            counts_after = counts_before
            break

        iteration_detail: dict[str, Any] = {}
        for sym, iid in instrument_ids.items():
            current_n = counts_before[sym]
            if current_n >= target_n:
                iteration_detail[sym] = {"n": current_n, "skipped": True}
                continue
            try:
                days = await _trading_days_for_symbol(db, sym, years=2.0)
                missing: list[datetime] = []
                for d in days:
                    if not await snapshot_exists_for_day(
                        db, symbol=sym, snapshot_date=d, source=SNAPSHOT_SOURCE_BACKFILL
                    ):
                        missing.append(d)
                todo = missing[:batch_size]
                created = 0
                snapshot_errors: list[str] = []
                for as_of in todo:
                    result = await generate_backfill_snapshot(
                        db,
                        instrument_id=iid,
                        symbol=sym,
                        as_of=as_of,
                        skip_existing=True,
                    )
                    if not result.skipped:
                        created += 1
                    elif result.reason and result.reason != "exists":
                        snapshot_errors.append(f"{as_of.date()}: {result.reason}")
                        logger.warning(
                            "backfill_day_failed",
                            symbol=sym,
                            as_of=as_of.isoformat(),
                            error=result.reason,
                        )
                iteration_detail[sym] = {
                    "n_before": current_n,
                    "missing_total": len(missing),
                    "batch_attempted": len(todo),
                    "created": created,
                    "errors": snapshot_errors[:10],
                }
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                failed[sym] = err
                logger.error(
                    "backfill_symbol_failed",
                    symbol=sym,
                    error=err,
                )
                iteration_detail[sym] = {
                    "n_before": current_n,
                    "error": err,
                }
                continue

        try:
            resolved = await resolve_all_backfill_snapshots(db, batch_limit=500, max_batches=50)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            logger.error("backfill_resolve_failed", error=err)
            summary["resolve_error"] = err
            resolved = 0

        counts_after = {sym: await scored_resolution_count(db, sym) for sym in instrument_ids}
        summary["symbols"] = {
            sym: {**iteration_detail.get(sym, {}), "n": counts_after[sym]}
            for sym in instrument_ids
        }
        summary["last_resolved"] = resolved
        if all(n >= target_n for n in counts_after.values()):
            break

    if not counts_after and instrument_ids:
        counts_after = {sym: await scored_resolution_count(db, sym) for sym in instrument_ids}

    report_rows = await compute_resolution_accuracy_report(
        db, symbols=symbols, sources=("backfill", "live")
    )
    summary["accuracy"] = report_to_json(report_rows)
    summary["markdown"] = report_to_markdown(report_rows)
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    return _finalize_backfill_summary(
        summary, target_n=target_n, counts=counts_after, failed=failed
    )
