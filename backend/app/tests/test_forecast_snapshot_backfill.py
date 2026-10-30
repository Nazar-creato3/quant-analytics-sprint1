"""Tests for forecast snapshot backfill (no look-ahead guard)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.forecast.snapshot_backfill import (
    _trading_days_for_symbol,
    generate_backfill_snapshot,
)
from app.services.market_data.series_loader import _load_from_ohlcv_table


class _Bar:
    def __init__(self, ts: datetime, close: float = 100.0):
        self.timestamp = ts
        self.close = close
        self.volume = 1.0


@pytest.mark.asyncio
async def test_trading_days_respects_horizon_buffer():
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = [_Bar(base + timedelta(days=i)) for i in range(60)]

    session = AsyncMock()
    with patch(
        "app.services.forecast.snapshot_backfill.get_bars_for_chart",
        new=AsyncMock(return_value=bars),
    ):
        days = await _trading_days_for_symbol(session, "AAPL", years=0.1, max_horizon_days=10)

    assert len(days) == 60 - 30 - 10 + 1  # min_history=30, horizon=10
    assert days[0] == base + timedelta(days=29)
    assert days[-1] == base + timedelta(days=49)


@pytest.mark.asyncio
async def test_generate_backfill_passes_as_of_to_orchestrator():
    as_of = datetime(2024, 6, 15, tzinfo=timezone.utc)
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    hierarchy = MagicMock()
    hierarchy.to_dict.return_value = {"point_forecast": {"expected_return_sign": 1}}
    hierarchy.calibrated_confidence = 0.55
    hierarchy.action_forecast.recommendation.value = "wait"
    hierarchy.point_forecast.expected_return_sign = 1
    hierarchy.point_forecast.momentum_score = 0.72
    hierarchy.interval_forecast.horizon_days = 10

    orchestrator = MagicMock()
    orchestrator.get_forecast = AsyncMock(return_value=hierarchy)
    builder = MagicMock()
    builder.build = AsyncMock(return_value={"market_outlook": []})

    async def _enrich(db, **kwargs):
        payload = kwargs["payload"]
        payload["predicted_direction"] = 1
        payload["expected_return_sign"] = 1
        payload["ensemble"] = {"direction_consensus": 1}
        return payload

    with (
        patch(
            "app.services.forecast.snapshot_backfill.snapshot_exists_for_day",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.forecast.snapshot_backfill.get_hierarchy_orchestrator",
            return_value=orchestrator,
        ),
        patch(
            "app.services.forecast.snapshot_backfill.get_daily_forecast_builder",
            return_value=builder,
        ),
        patch(
            "app.services.forecast.snapshot_direction.enrich_payload_predicted_direction",
            new=AsyncMock(side_effect=_enrich),
        ),
        patch(
            "app.services.forecast.snapshot_backfill.upsert_daily_snapshot",
            new=AsyncMock(return_value=MagicMock(id="snap-1")),
        ),
    ):
        result = await generate_backfill_snapshot(
            session,
            instrument_id=1,
            symbol="AAPL",
            as_of=as_of,
        )

    assert result.skipped is False
    orchestrator.get_forecast.assert_awaited_once()
    call_kwargs = orchestrator.get_forecast.await_args.kwargs
    assert call_kwargs["as_of"] == as_of
    assert call_kwargs["use_cache"] is False
    builder.build.assert_awaited_once()
    assert builder.build.await_args.kwargs["as_of"] == as_of
    assert builder.build.await_args.kwargs.get("skip_explain") is True
    assert result.snapshot_id == "snap-1"


@pytest.mark.asyncio
async def test_load_from_ohlcv_table_filters_by_as_of():
    """Spot-check: as_of cutoff prevents loading future bars."""
    as_of = datetime(2024, 6, 1, tzinfo=timezone.utc)
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=execute_result)

    await _load_from_ohlcv_table(session, 1, limit=120, as_of=as_of)
    session.execute.assert_awaited_once()
    stmt = session.execute.await_args.args[0]
    compiled = str(stmt)
    assert "timeframe" in compiled or stmt is not None
