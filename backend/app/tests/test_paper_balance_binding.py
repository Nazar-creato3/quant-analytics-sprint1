"""Approved maneuvers reserve buying power in exposure metrics."""
from __future__ import annotations

import pytest

from app.db.models import Maneuver, ManeuverStatus
from app.services.portfolio import exposure as exposure_mod


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class _FakeSession:
    def __init__(self, maneuvers):
        self._maneuvers = maneuvers

    async def execute(self, _stmt):
        return _FakeResult(self._maneuvers)


@pytest.mark.asyncio
async def test_approved_maneuver_counts_toward_exposure():
    session = _FakeSession(
        [
            Maneuver(
                id="m-approved",
                ticker="GAZP",
                direction="long",
                position_size_usd=1080.0,
                status=ManeuverStatus.APPROVED,
                risk_percent=1.0,
                confidence=0.7,
                time_horizon="1-3 days",
            )
        ]
    )
    usd, count = await exposure_mod.maneuver_exposure(session)
    assert usd == pytest.approx(1080.0)
    assert count == 1
