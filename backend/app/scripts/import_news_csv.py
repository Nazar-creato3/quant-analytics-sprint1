"""CLI: bulk-import financial news CSV and politics JSON datasets into ``news_articles``.

Usage (from ``backend/``):

    python -m app.scripts.import_news_csv
    python -m app.scripts.import_news_csv --data-dir "../новостные данные"
    python -m app.scripts.import_news_csv --include-politics
    python -m app.scripts.import_news_csv --dry-run --limit 100
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.services.news.csv_bulk_import import default_news_csv_dir, import_csv_news
from app.services.news.politics_json_import import (
    import_politics_json_news,
    politics_dirs_present,
)

logger = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import financial news CSV and politics JSON files into news_articles.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory with Financial*.csv and/or Politics_* folders (default: NEWS_CSV_DATA_DIR)",
    )
    parser.add_argument(
        "--include-politics",
        action="store_true",
        help="Import Politics_positive_* / Politics_negative_* JSON folders",
    )
    parser.add_argument(
        "--skip-politics",
        action="store_true",
        help="Skip politics JSON import even when Politics_* folders are present",
    )
    parser.add_argument(
        "--skip-csv",
        action="store_true",
        help="Skip Financial*.csv import",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count rows without writing to the database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of unique rows to process per importer (for testing)",
    )
    return parser


def _print_stats(label: str, stats) -> None:
    print(
        f"{label}: files={stats.files_seen} parsed={stats.rows_parsed} "
        f"inserted={stats.inserted} skipped_duplicate={stats.skipped_duplicate} "
        f"invalid={stats.skipped_invalid}"
    )
    if stats.errors:
        for err in stats.errors:
            print(f"{label} error: {err}", file=sys.stderr)


async def _run(args: argparse.Namespace) -> int:
    data_dir = args.data_dir or default_news_csv_dir()
    data_path = Path(data_dir).expanduser().resolve()
    import_politics = args.include_politics or (
        not args.skip_politics and politics_dirs_present(data_path)
    )

    exit_code = 0
    async with AsyncSessionLocal() as session:
        if not args.skip_csv:
            csv_stats = await import_csv_news(
                session,
                data_path,
                dry_run=args.dry_run,
                limit=args.limit,
            )
            _print_stats("csv", csv_stats)
            if csv_stats.errors:
                exit_code = 1

        if import_politics:
            politics_stats = await import_politics_json_news(
                session,
                data_path,
                dry_run=args.dry_run,
                limit=args.limit,
            )
            _print_stats("politics", politics_stats)
            if politics_stats.errors:
                exit_code = 1
        else:
            print("politics: skipped (no Politics_* folders detected; use --include-politics)")

    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except FileNotFoundError as exc:
        logger.error("News import failed", error=str(exc))
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
