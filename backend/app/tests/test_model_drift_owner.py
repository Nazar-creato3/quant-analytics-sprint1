"""Model drift must not aggregate every user's closed maneuvers."""
from __future__ import annotations

import asyncio

from app.services.monitoring.model_drift import _live_direction_accuracy, empty_model_drift


def test_empty_drift_snapshot() -> None:
    out = empty_model_drift()
    assert out.live_accuracy is None
    assert out.alert is False
    assert out.per_regime == {}


def test_blank_owner_skips_global_drift() -> None:
    acc, regimes = asyncio.run(_live_direction_accuracy(None, owner_user_id=""))  # type: ignore[arg-type]
    assert acc is None
    assert regimes == {}
