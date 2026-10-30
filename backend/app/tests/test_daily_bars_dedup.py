"""A daily session stored twice (00:00 and 04:00 UTC) must count once."""
from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.schemas import OHLCVBarOut
from app.services.market_data.bars import _chart_bars


def _bar(day: int, hour: int, tf: str = "1d") -> OHLCVBarOut:
    return OHLCVBarOut(
        ticker="AAPL", timestamp=datetime(2026, 10, day, hour, tzinfo=timezone.utc), timeframe=tf,
        open=1, high=1, low=1, close=float(day), volume=1,
    )


def test_daily_duplicates_collapse() -> None:
    out = _chart_bars([_bar(d, h) for d in (21, 22, 23) for h in (0, 4)])
    assert [b.timestamp.day for b in out] == [21, 22, 23]


def test_intraday_untouched() -> None:
    bars = [_bar(23, h, "1h") for h in (14, 15, 16)]
    assert len(_chart_bars(bars)) == 3
