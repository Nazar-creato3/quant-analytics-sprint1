"""Tests for backfill_until_target batch helper."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.forecast.snapshot_backfill import backfill_until_target


@pytest.mark.asyncio
async def test_backfill_until_target_stops_when_n_reached():
    session = AsyncMock()

    async def _counts(db, symbol, sources=("backfill", "live")):
        return 100 if symbol == "AAPL" else 50

    with (
        patch(
            "app.services.forecast.snapshot_backfill.scored_resolution_count",
            side_effect=_counts,
        ),
        patch(
            "app.services.forecast.snapshot_backfill._trading_days_for_symbol",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.forecast.snapshot_backfill.resolve_all_backfill_snapshots",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.services.forecast.snapshot_backfill.compute_resolution_accuracy_report",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.forecast.snapshot_backfill.report_to_json",
            return_value={"rows": []},
        ),
        patch(
            "app.services.forecast.snapshot_backfill.report_to_markdown",
            return_value="",
        ),
    ):
        exec_result = MagicMock()
        exec_result.scalar.return_value = 1
        session.execute = AsyncMock(return_value=exec_result)
        result = await backfill_until_target(
            session,
            symbols=("AAPL",),
            target_n=100,
            batch_size=5,
            max_iterations=2,
        )
    assert result["iterations"] >= 1
    assert result["status"] in {"complete", "incomplete", "partial_failure", "failed"}
    assert "succeeded" in result
    assert "failed" in result


@pytest.mark.asyncio
async def test_backfill_until_target_continues_after_symbol_error():
    session = AsyncMock()
    counts = {"AAPL": 20, "MSFT": 0}

    async def _counts(db, symbol, sources=("backfill", "live")):
        return counts[symbol]

    async def _generate(*args, **kwargs):
        if kwargs.get("symbol") == "MSFT":
            raise RuntimeError("msft boom")
        return type("R", (), {"skipped": False, "reason": ""})()

    with (
        patch(
            "app.services.forecast.snapshot_backfill.scored_resolution_count",
            side_effect=_counts,
        ),
        patch(
            "app.services.forecast.snapshot_backfill._trading_days_for_symbol",
            new=AsyncMock(return_value=[datetime.now(timezone.utc)]),
        ),
        patch(
            "app.services.forecast.snapshot_backfill.snapshot_exists_for_day",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.forecast.snapshot_backfill.generate_backfill_snapshot",
            side_effect=_generate,
        ),
        patch(
            "app.services.forecast.snapshot_backfill.resolve_all_backfill_snapshots",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.services.forecast.snapshot_backfill.compute_resolution_accuracy_report",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.forecast.snapshot_backfill.report_to_json",
            return_value={"rows": []},
        ),
        patch(
            "app.services.forecast.snapshot_backfill.report_to_markdown",
            return_value="",
        ),
    ):
        exec_result = MagicMock()
        exec_result.scalar.return_value = 1
        session.execute = AsyncMock(return_value=exec_result)
        result = await backfill_until_target(
            session,
            symbols=("AAPL", "MSFT"),
            target_n=100,
            batch_size=1,
            max_iterations=1,
        )
    assert result["status"] == "partial_failure"
    assert "MSFT" in result["failed"]
    assert "msft boom" in result["failed"]["MSFT"]
    assert "AAPL" not in result["failed"]
    assert result["symbols"]["AAPL"]["created"] == 1
