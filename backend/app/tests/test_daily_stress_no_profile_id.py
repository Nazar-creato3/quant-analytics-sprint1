"""GA16-274: daily stress result must not include user ids."""
from __future__ import annotations

from types import SimpleNamespace

from app.tasks.stress_harness import public_daily_stress_row


def test_daily_stress_row_has_no_profile_id() -> None:
    report = SimpleNamespace(
        max_loss_usd=12.5,
        worst_scenario=SimpleNamespace(scenario_name=SimpleNamespace(value="crash")),
        positions_to_review=[1, 2],
    )
    row = public_daily_stress_row(report)
    assert "profile_id" not in row
    assert "worst_scenario" not in row
    assert row["max_loss_usd"] == 12.5
    assert row["positions_to_review"] == 2
