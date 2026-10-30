"""GA-021…GA-037: market_data chart/binance and ops live_hooks fail closed."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.schemas import OHLCVBarOut
from app.services.market_data.bars import _chart_bars
from app.services.market_data import binance_spot
from app.services.ops_desk.live_hooks import reject_new_order


def test_ga021_chart_bars_skips_nonpositive_close() -> None:
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        OHLCVBarOut(
            ticker="SBER",
            timestamp=ts,
            timeframe="1d",
            open=1,
            high=1,
            low=1,
            close=0,
            volume=1,
        ),
        OHLCVBarOut(
            ticker="SBER",
            timestamp=ts,
            timeframe="1d",
            open=1,
            high=1,
            low=1,
            close=10,
            volume=1,
        ),
    ]
    good = _chart_bars(rows)
    assert len(good) == 1
    assert good[0].close == 10


@pytest.mark.asyncio
async def test_ga022_026_binance_quote_refuses_missing_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty_get(path, params=None):  # noqa: ANN001, ARG001
        return {}

    async def no_cache(*_a, **_k):
        return None

    async def noop_set(*_a, **_k):
        return None

    monkeypatch.setattr(binance_spot, "_binance_get", empty_get)
    monkeypatch.setattr(binance_spot, "cache_get", no_cache)
    monkeypatch.setattr(binance_spot, "cache_set", noop_set)
    monkeypatch.setattr(binance_spot, "get_ws_live_price", no_cache)
    assert await binance_spot.get_crypto_quote("BTC-USD", force_refresh=True) is None


def test_ga036_037_mandate_failure_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("ips down")

    monkeypatch.setattr("app.services.platform_desk.mandate.load_ips", boom)
    msg = reject_new_order(
        ticker="AAA",
        side="buy",
        qty=1.0,
        price=10.0,
        settings_cap=250,
        account_total=250,
        sensors={"day_pnl_frac": 0.0, "dd_frac": 0.0, "last_bar": datetime.now(timezone.utc), "broker_connected": True},
        user_id="u1",
    )
    assert msg == "mandate:unavailable"
