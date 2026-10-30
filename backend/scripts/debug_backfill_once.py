#!/usr/bin/env python3
"""One-shot backfill debug with full traceback."""
from __future__ import annotations

import asyncio
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.services.forecast.daily_builder import get_daily_forecast_builder
from app.services.instrument.resolver import resolve_or_create_instrument
from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator


async def main() -> None:
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as session:
        inst = await resolve_or_create_instrument(session, "AAPL")
        print("instrument", inst.id, inst.symbol)
        orchestrator = get_hierarchy_orchestrator()
        builder = get_daily_forecast_builder()
        try:
            print("--- orchestrator.get_forecast ---")
            hierarchy = await orchestrator.get_forecast(
                session,
                inst.id,
                symbol=inst.symbol,
                include_narrative=False,
                use_cache=False,
                as_of=as_of,
            )
            print("hierarchy ok", hierarchy.calibrated_confidence)
        except Exception:
            traceback.print_exc()
            return
        try:
            print("--- builder.build ---")
            payload = await builder.build(
                session,
                instrument_id=inst.id,
                symbol=inst.symbol,
                as_of=as_of,
                skip_explain=True,
            )
            print("payload keys", list(payload.keys())[:8])
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
