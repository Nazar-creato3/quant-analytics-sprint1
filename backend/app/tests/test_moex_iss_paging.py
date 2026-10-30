"""ISS candles come 500 per page, oldest first: the loader must read every page."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.services.market_data import moex_spot

COLS = ["open", "close", "high", "low", "value", "volume", "begin", "end"]


def _rows(n: int, start: date) -> list[list]:
    out = []
    for i in range(n):
        d = (start + timedelta(days=i)).isoformat()
        out.append([100.0, 100.0 + i, 101.0, 99.0, 1.0, 10.0, f"{d} 00:00:00", f"{d} 23:59:59"])
    return out


class _Resp:
    def __init__(self, rows: list[list]) -> None:
        self._rows = rows

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"candles": {"columns": COLS, "data": self._rows}}


class _Client:
    calls: list[int] = []

    def __init__(self, *a, **k) -> None:
        all_rows = _rows(1200, date(2022, 1, 1))
        self._all = all_rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        start = int((params or {}).get("start", 0))
        _Client.calls.append(start)
        return _Resp(self._all[start : start + 500])


@pytest.mark.asyncio
async def test_iss_bars_read_all_pages_and_keep_latest():
    _Client.calls = []
    with patch.object(moex_spot.httpx, "AsyncClient", _Client):
        bars = await moex_spot._fetch_moex_iss_bars("SBER", "1d", 1000)
    assert _Client.calls == [0, 500, 1000]
    assert len(bars) == 1000
    assert bars[-1]["close"] == 100.0 + 1199  # newest candle is present
