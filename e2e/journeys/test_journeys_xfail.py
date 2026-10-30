"""User journeys — expected-fail until the named phase lands (Prompt 01)."""
from __future__ import annotations

import pytest

JOURNEYS = [
    ("register", "02"),
    ("connect_test_account", "24"),
    ("forecast_to_paper_order", "11A"),
    ("start_paper_bot", "25"),
    ("limit_notification", "29"),
]


@pytest.mark.parametrize("journey,phase", JOURNEYS)
def test_journey_pending(journey: str, phase: str):
    pytest.xfail(f"journey {journey} turns green in prompt {phase}")
