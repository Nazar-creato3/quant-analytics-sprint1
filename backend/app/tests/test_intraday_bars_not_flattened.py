"""Regression: 1h bars must keep their own OHLC (were flattened to the day's last close)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.api.v1.endpoints.market import _adjust_chart_bars
from app.schemas.schemas import OHLCVBarOut


def _bars() -> list[OHLCVBarOut]:
    start = datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc)
    rows = []
    for i, (o, h, l, c) in enumerate([(217.8, 217.9, 216.8, 217.1), (217.1, 218.3, 216.9, 217.9), (217.9, 218.3, 216.8, 217.0)]):
        rows.append(
            OHLCVBarOut(ticker="NVDA", timestamp=start + timedelta(hours=i), timeframe="1h", open=o, high=h, low=l, close=c, volume=1000)
        )
    return rows


def test_intraday_bars_keep_their_own_prices():
    out = _adjust_chart_bars(_bars(), "split_adj", "1h")
    assert [b.close for b in out] == [217.1, 217.9, 217.0]
    assert len({(b.open, b.close) for b in out}) == 3


def test_daily_adjust_still_runs():
    daily = [b.model_copy(update={"timeframe": "1d", "timestamp": b.timestamp + timedelta(days=i)}) for i, b in enumerate(_bars())]
    out = _adjust_chart_bars(daily, "split_adj", "1d")
    assert [round(b.close, 4) for b in out] == [217.1, 217.9, 217.0]


def test_adjust_ohlc_keeps_intraday_shape_even_when_called_directly():
    from datetime import date
    from decimal import Decimal as D

    from app.services.market_data.series import OhlcBar, adjust_ohlc

    day = date(2026, 10, 19)
    bars = [OhlcBar(day, D("10"), D("11"), D("9"), D(c), D("1")) for c in ("10", "10.5", "10.2")]
    out = adjust_ohlc(bars, [], "split_adj")
    assert [b.close for b in out] == [D("10"), D("10.5"), D("10.2")]
