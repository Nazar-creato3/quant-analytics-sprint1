"""GA16-272: an empty live tape is not all-good with 100% fill."""
from __future__ import annotations

from app.services.execution.parity import nightly_parity


def test_empty_live_tape_is_not_all_good() -> None:
    report = nightly_parity([])
    assert report.ok is False
    assert report.paper_fill == 0.0
    assert report.live_fill == 0.0
    assert "нет данных" in report.reasons
