"""Print forecast_snapshot_resolutions row counts."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.db.models import ForecastSnapshot, ForecastSnapshotResolution
from app.db.session import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as session:
        resolutions = (
            await session.execute(select(func.count()).select_from(ForecastSnapshotResolution))
        ).scalar()
        snapshots = (
            await session.execute(select(func.count()).select_from(ForecastSnapshot))
        ).scalar()
        print(f"forecast_snapshots: {snapshots}")
        print(f"forecast_snapshot_resolutions: {resolutions}")


if __name__ == "__main__":
    asyncio.run(main())
