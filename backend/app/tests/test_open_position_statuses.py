"""Open position status filter must include approved (decision-only approve flow)."""
from __future__ import annotations

from app.db.models import ManeuverStatus
from app.services.portfolio.exposure import OPEN_EXPOSURE_STATUSES


def test_open_exposure_includes_approved_executing_filled():
    values = {s.value for s in OPEN_EXPOSURE_STATUSES}
    assert values == {"approved", "executing", "filled"}


def test_approved_is_open_position_status():
    assert ManeuverStatus.APPROVED in OPEN_EXPOSURE_STATUSES
