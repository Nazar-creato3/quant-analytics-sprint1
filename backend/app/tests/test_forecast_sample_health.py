"""Health sample-size counting must match raw scored rows (no horizon/source filter)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import ForecastSnapshot, ForecastSnapshotResolution
from app.services.forecast.direction_accuracy import DIRECTION_RETURN_THRESHOLD
from app.services.forecast.snapshot_backfill import unfiltered_resolution_counts
from app.services.health.reporter import check_forecast_direction_accuracy, check_forecast_sample_growth
from app.services.terminal_platform.market.hours import nyse_regular_session_elapsed
from app.utils.helpers import new_uuid


async def _sqlite_session() -> tuple:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(ForecastSnapshot.__table__.create)
        await conn.run_sync(ForecastSnapshotResolution.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, factory


def _resolution(
    *,
    symbol: str,
    predicted_direction: int,
    realized_return: float,
    hit: bool,
    horizon_days: int = 10,
    snapshot_id: str | None = None,
    resolved_at: datetime | None = None,
) -> ForecastSnapshotResolution:
    now = resolved_at or datetime(2026, 8, 20, tzinfo=timezone.utc)
    return ForecastSnapshotResolution(
        id=new_uuid(),
        snapshot_id=snapshot_id or new_uuid(),
        symbol=symbol,
        snapshot_date=now - timedelta(days=10),
        horizon_days=horizon_days,
        predicted_direction=predicted_direction,
        realized_return=realized_return,
        direction_hit=hit,
        resolved_at=now,
    )


@pytest.mark.asyncio
async def test_health_scored_n_matches_raw_table_for_seeded_dataset():
    engine, factory = await _sqlite_session()
    async with factory() as session:
        rows = [
            _resolution(symbol="AAPL", predicted_direction=1, realized_return=0.01, hit=True, horizon_days=10),
            _resolution(symbol="AAPL", predicted_direction=-1, realized_return=-0.02, hit=True, horizon_days=1),
            _resolution(symbol="AAPL", predicted_direction=0, realized_return=0.05, hit=False),  # unscored
            _resolution(symbol="MSFT", predicted_direction=1, realized_return=0.0001, hit=False),  # unscored (flat)
            _resolution(symbol="MSFT", predicted_direction=1, realized_return=0.03, hit=False, horizon_days=10),
            _resolution(symbol="SPY", predicted_direction=-1, realized_return=0.04, hit=False, horizon_days=5),
        ]
        session.add_all(rows)
        await session.commit()

        counts = await unfiltered_resolution_counts(session, ("AAPL", "MSFT", "SPY"))

        def _is_scored(r: ForecastSnapshotResolution) -> bool:
            return r.predicted_direction != 0 and abs(r.realized_return) > DIRECTION_RETURN_THRESHOLD

        expected_raw = {"AAPL": 3, "MSFT": 2, "SPY": 1}
        expected_scored = {
            "AAPL": sum(1 for r in rows if r.symbol == "AAPL" and _is_scored(r)),
            "MSFT": sum(1 for r in rows if r.symbol == "MSFT" and _is_scored(r)),
            "SPY": sum(1 for r in rows if r.symbol == "SPY" and _is_scored(r)),
        }
        for sym in ("AAPL", "MSFT", "SPY"):
            assert counts[sym].raw_n == expected_raw[sym]
            assert counts[sym].scored_n == expected_scored[sym]
        assert counts["AAPL"].scored_n == 2
        assert counts["MSFT"].scored_n == 1
        assert counts["SPY"].scored_n == 1
        assert counts["AAPL"].raw_n > counts["AAPL"].scored_n

        class _Ctx:
            async def __aenter__(self_inner):
                return session

            async def __aexit__(self_inner, *args):
                return False

        with patch("app.db.session.AsyncSessionLocal", return_value=_Ctx()):
            health = await check_forecast_direction_accuracy()
        assert health["sample_n"]["AAPL"] == counts["AAPL"].scored_n
        assert health["sample_n"]["MSFT"] == counts["MSFT"].scored_n
        assert health["sample_n"]["SPY"] == counts["SPY"].scored_n
        assert health["raw_n"]["AAPL"] == counts["AAPL"].raw_n
        assert "h=" not in (health.get("error") or "")
    await engine.dispose()


def test_nyse_session_elapsed_weekday_vs_weekend():
    friday_open = datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc)  # 10:00 ET
    friday_close = datetime(2026, 8, 21, 21, 0, tzinfo=timezone.utc)
    assert nyse_regular_session_elapsed(friday_open, friday_close) is True
    sat = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    sun = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    assert nyse_regular_session_elapsed(sat, sun) is False


@pytest.mark.asyncio
async def test_sample_growth_fails_when_n_below_target_and_no_new_rows():
    from app.services.forecast.snapshot_backfill import UnfilteredResolutionCount

    totals = {
        "AAPL": UnfilteredResolutionCount("AAPL", raw_n=4, scored_n=4, hits=2),
        "MSFT": UnfilteredResolutionCount("MSFT", raw_n=0, scored_n=0, hits=0),
        "SPY": UnfilteredResolutionCount("SPY", raw_n=0, scored_n=0, hits=0),
    }

    class _Ctx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return False

    with (
        patch("app.db.session.AsyncSessionLocal", return_value=_Ctx()),
        patch(
            "app.services.forecast.snapshot_backfill.unfiltered_resolution_counts",
            return_value=totals,
        ),
        patch(
            "app.services.forecast.snapshot_backfill.scored_resolutions_since",
            return_value={"AAPL": 0, "MSFT": 0, "SPY": 0},
        ),
        patch(
            "app.services.forecast.snapshot_backfill.mature_unresolved_counts",
            return_value={"AAPL": 0, "MSFT": 0, "SPY": 0},
        ),
        patch(
            "app.services.terminal_platform.market.hours.nyse_regular_session_elapsed",
            return_value=True,
        ),
    ):
        row = await check_forecast_sample_growth()
    assert row["status"] == "failed"
    assert "MSFT" in (row.get("error") or "")
    assert "SPY" in (row.get("error") or "")
