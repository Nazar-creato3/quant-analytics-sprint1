#!/usr/bin/env python3
"""Backfill forecast snapshots using the live pipeline (point-in-time, no look-ahead).

Usage:
  cd backend && python scripts/backfill_forecast_snapshots.py
  python scripts/backfill_forecast_snapshots.py --tickers AAPL MSFT --years 1
  python scripts/backfill_forecast_snapshots.py --resolve-only
  python scripts/backfill_forecast_snapshots.py --report-only --output report.json

Live ensemble suppression uses source=live resolutions only; backfill rows are for
track-record evaluation and do not affect production direction suppression.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.forecast.snapshot_backfill import (
    DEFAULT_BACKFILL_TICKERS,
    backfill_symbol,
    compute_resolution_accuracy_report,
    report_to_json,
    report_to_markdown,
    resolve_all_backfill_snapshots,
)
from app.services.instrument.resolver import resolve_or_create_instrument
from app.utils.wilson_ci import format_accuracy_with_ci_ru


async def _run_backfill(args: argparse.Namespace) -> dict:
    tickers = [t.strip().upper() for t in (args.tickers or DEFAULT_BACKFILL_TICKERS) if t.strip()]
    results: dict = {"tickers": tickers, "symbols": {}, "resolved": 0, "report": []}

    async with AsyncSessionLocal() as session:
        if not args.report_only:
            for symbol in tickers:
                try:
                    instrument = await resolve_or_create_instrument(session, symbol)
                except ValueError as exc:
                    results["symbols"][symbol] = {"status": "error", "reason": str(exc)}
                    continue
                if args.resolve_only:
                    continue
                sym_result = await backfill_symbol(
                    session,
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    years=args.years,
                    sample_every=args.sample_every,
                    max_days=args.max_days,
                    force=args.force,
                )
                results["symbols"][symbol] = sym_result

            if not args.no_resolve:
                results["resolved"] = await resolve_all_backfill_snapshots(session)

        report = await compute_resolution_accuracy_report(
            session,
            symbols=tuple(tickers),
            sources=tuple(args.sources.split(",")) if args.sources else ("backfill", "live"),
        )
        results["report"] = [row.to_dict() for row in report]

    return results


def _print_summary(results: dict) -> None:
    print("=== Backfill summary ===")
    for symbol, data in results.get("symbols", {}).items():
        if isinstance(data, dict) and "created" in data:
            print(f"  {symbol}: created={data['created']} skipped={data['skipped']} days={data['trading_days']}")
    print(f"Resolved rows (this run): {results.get('resolved', 0)}")
    print("\n=== Accuracy (Wilson 95% CI) ===")
    for row in results.get("report", []):
        formatted = format_accuracy_with_ci_ru(
            row.get("accuracy"),
            ci_low=row.get("ci_low"),
            ci_high=row.get("ci_high"),
            sample_size=row.get("n"),
        )
        print(f"  {row['symbol']} h{row['horizon_days']}: {formatted}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill forecast snapshots (live pipeline, point-in-time)")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=list(DEFAULT_BACKFILL_TICKERS),
        help="Symbols to backfill (default: AAPL MSFT SPY BTC-USD)",
    )
    parser.add_argument("--years", type=float, default=2.0, help="Years of history (default: 2)")
    parser.add_argument("--sample-every", type=int, default=1, help="Use every Nth trading day (default: 1)")
    parser.add_argument("--max-days", type=int, default=None, help="Cap number of days per symbol")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing backfill snapshots for each day (also deletes their resolutions)",
    )
    parser.add_argument("--resolve-only", action="store_true", help="Skip generation; only resolve mature snapshots")
    parser.add_argument("--no-resolve", action="store_true", help="Skip resolution after generation")
    parser.add_argument("--report-only", action="store_true", help="Only print/save accuracy report")
    parser.add_argument(
        "--sources",
        default="backfill,live",
        help="Comma-separated snapshot sources for report (default: backfill,live)",
    )
    parser.add_argument("--output", type=str, default=None, help="Write JSON report to path")
    parser.add_argument("--markdown", type=str, default=None, help="Write markdown report to path")
    args = parser.parse_args()

    print(f"Database: {settings.DATABASE_URL_SYNC[:40]}...")
    results = asyncio.run(_run_backfill(args))
    _print_summary(results)

    report_rows = results.get("report", [])
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(report_to_json_from_dict(report_rows), indent=2), encoding="utf-8")
        print(f"\nJSON report: {out_path}")
    if args.markdown:
        md_path = Path(args.markdown)
        from app.services.forecast.snapshot_backfill import AccuracyReportRow

        rows = [
            AccuracyReportRow(
                symbol=r["symbol"],
                horizon_days=r["horizon_days"],
                sample_size=r["n"],
                accuracy=r.get("accuracy"),
                ci_low=r.get("ci_low"),
                ci_high=r.get("ci_high"),
                hits=r.get("hits", 0),
            )
            for r in report_rows
        ]
        md_path.write_text(report_to_markdown(rows), encoding="utf-8")
        print(f"Markdown report: {md_path}")


def report_to_json_from_dict(rows: list[dict]) -> dict:
    from datetime import datetime, timezone

    return {"generated_at": datetime.now(timezone.utc).isoformat(), "rows": rows}


if __name__ == "__main__":
    main()
