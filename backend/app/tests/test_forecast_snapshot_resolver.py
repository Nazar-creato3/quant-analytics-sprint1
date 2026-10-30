"""Tests for forecast snapshot resolution pipeline."""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.forecast.snapshot_resolver import (
    _bars_needed_for_snapshot,
    _extract_prediction,
    _log_aci_coverage,
)


class _Snap:
    def __init__(self, payload: dict):
        self.payload = payload


def test_extract_prediction_from_payload_fields():
    snap = _Snap(
        {
            "predicted_direction": -1,
            "horizon_days": 5,
        }
    )
    direction, horizon = _extract_prediction(snap)  # type: ignore[arg-type]
    assert direction == -1
    assert horizon == 5


def test_extract_prediction_from_hierarchy_fallback():
    snap = _Snap(
        {
            "hierarchy_output": {
                "point_forecast": {"expected_return_sign": 1},
                "interval_forecast": {"horizon_days": 10},
            }
        }
    )
    direction, horizon = _extract_prediction(snap)  # type: ignore[arg-type]
    assert direction == 1
    assert horizon == 10


def test_bars_needed_covers_old_backfill_snapshot_date():
    """Old backfill rows must request enough recent bars to include snapshot_date."""
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    snap = datetime(2025, 7, 23, tzinfo=timezone.utc)
    needed = _bars_needed_for_snapshot(snap, horizon_days=10, now=now)
    # days_since=381 + horizon + slack; must exceed naive horizon+5=15
    assert needed >= 381 + 10
    assert needed > 15


def test_bars_needed_recent_snapshot_uses_small_window():
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    snap = datetime(2026, 7, 20, tzinfo=timezone.utc)
    needed = _bars_needed_for_snapshot(snap, horizon_days=10, now=now)
    assert needed == max(15, 19 + 10 + 10)


def test_log_aci_coverage_does_not_raise_on_duplicate_symbol_key():
    """Regression: structlog TypeError on symbol= + aci_update['symbol'] aborted resolve."""
    aci_update = {
        "updated": True,
        "symbol": "SPY",
        "aci_70": {"covered": True, "alpha_t": 0.1},
    }
    _log_aci_coverage("SPY", aci_update)
