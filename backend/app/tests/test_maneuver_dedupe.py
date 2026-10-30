from app.services.risk.maneuver_dedupe import maneuver_content_key


def test_same_thesis_same_key():
    a = maneuver_content_key("msft", "short", 0.52, "RSI 56  MACD bearish")
    b = maneuver_content_key("MSFT", "SHORT", 0.521, "RSI 56 MACD bearish")
    assert a == b


def test_different_ticker_different_key():
    assert maneuver_content_key("MSFT", "short", 0.52, "same") != maneuver_content_key(
        "ETH-USD", "short", 0.52, "same"
    )


import pytest

from app.db.models import ManeuverStatus
from app.services.risk import maneuver_dedupe


class _M:
    def __init__(self, ticker, status, rationale="same"):
        self.ticker, self.direction, self.confidence = ticker, "long", 0.55
        self.rationale, self.status = rationale, status


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return _Res(self.rows)


@pytest.mark.asyncio
async def test_pending_repeat_is_withdrawn_not_dropped():
    old_same = _M("SBER", ManeuverStatus.PENDING)
    old_other = _M("GAZP", ManeuverStatus.PENDING, rationale="other idea")
    new_keys = {maneuver_content_key("SBER", "long", 0.55, "same")}
    n = await maneuver_dedupe.supersede_pending_duplicates(
        _Session([old_same, old_other]), user_id="u1", new_keys=new_keys
    )
    assert n == 1
    assert old_same.status == ManeuverStatus.INVALIDATED
    assert old_other.status == ManeuverStatus.PENDING


def test_pending_is_not_an_acted_status():
    assert ManeuverStatus.PENDING not in maneuver_dedupe._ACTED_STATUSES
    assert ManeuverStatus.REJECTED in maneuver_dedupe._ACTED_STATUSES
