"""Idempotent Eurostat bulk extract + macro registry refresh."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import _REPO_ROOT  # noqa: E402


async def _run(
    *,
    data_dir: Path | None,
    store_dir: Path | None,
    source_ids: list[str] | None,
    force_extract: bool,
    skip_refresh: bool,
) -> None:
    if data_dir is not None:
        os.environ["EUROSTAT_DATA_DIR"] = str(data_dir)
    if store_dir is not None:
        os.environ["EUROSTAT_STORE_DIR"] = str(store_dir)

    from app.core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    from app.services.macro_registry.eurostat.bulk import discover_data_roots, extract_datasets
    from app.services.macro_registry.eurostat.indicators import EUROSTAT_INDICATORS
    from app.services.macro_registry.seed import MACRO_SOURCE_SEED
    from app.services.macro_registry.service import MacroRegistryService

    roots = discover_data_roots(settings.EUROSTAT_DATA_DIR, _REPO_ROOT)
    store = Path(settings.EUROSTAT_STORE_DIR)
    extract_status = extract_datasets(store, roots, EUROSTAT_INDICATORS, force=force_extract)
    print("extract:", extract_status)

    if skip_refresh:
        return

    service = MacroRegistryService()
    euro_sources = [
        row["source_id"]
        for row in MACRO_SOURCE_SEED
        if str(row.get("category")) == "regional"
    ]
    targets = source_ids or euro_sources

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await service.seed_registry(session)
        for source_id in targets:
            try:
                result = await service.refresh_source(session, source_id)
                print(f"{source_id}: {result}")
            except FileNotFoundError as exc:
                print(f"{source_id}: skipped ({exc})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Eurostat bulk CSV and refresh macro registry")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory with ESTAT_downloads_data_*.zip (default: EUROSTAT_DATA_DIR / repo)",
    )
    parser.add_argument(
        "--store-dir",
        type=Path,
        default=None,
        help="Extracted CSV store (default: backend/data/eurostat)",
    )
    parser.add_argument(
        "--source-id",
        action="append",
        dest="source_ids",
        help="Refresh only this registry source_id (repeatable)",
    )
    parser.add_argument(
        "--force-extract",
        action="store_true",
        help="Re-extract CSV even when zip fingerprint unchanged",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Only extract CSV/manifest; do not write macro DB rows",
    )
    args = parser.parse_args()
    asyncio.run(
        _run(
            data_dir=args.data_dir,
            store_dir=args.store_dir,
            source_ids=args.source_ids,
            force_extract=args.force_extract,
            skip_refresh=args.skip_refresh,
        )
    )


if __name__ == "__main__":
    main()
