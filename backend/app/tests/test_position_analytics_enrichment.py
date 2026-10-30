"""Position list enrichment: quotes, NaN-safe SL/TP, P&L helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.schemas import ManeuverOut, ManeuverStatus, StrategyType
from app.services.portfolio import position_analytics as pa


def _maneuver(**kwargs):
    base = dict(
        id="m1",
        rank=1,
        ticker="MSFT",
        strategy_type=StrategyType.TREND_FOLLOWING,
        direction="long",
        entry_zone_low=400.0,
        entry_zone_high=410.0,
        exit_zone_low=430.0,
        exit_zone_high=440.0,
        stop_loss=float("nan"),
        take_profit=float("nan"),
        invalidation_level=395.0,
        risk_percent=1.0,
        position_size_usd=2000.0,
        confidence=0.7,
        time_horizon="5–10 дней",
        status=ManeuverStatus.FILLED,
        trading_mode="paper",
        fill_price=405.0,
        filled_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_maneuver_sl_tp_fallback_from_zones():
    m = _maneuver()
    assert pa.maneuver_stop_loss(m) == pytest.approx(395.0)
    assert pa.maneuver_take_profit(m) == pytest.approx(435.0)


def test_display_sl_tp_fallback_long():
    m = _maneuver(stop_loss=None, take_profit=None, invalidation_level=None, exit_zone_low=None, exit_zone_high=None)
    sl, tp = pa.display_sl_tp_fallback(m)
    assert sl is not None and tp is not None
    assert sl < m.fill_price < tp


def test_maneuver_out_recovers_nan_sl_tp_from_zones():
    m = _maneuver()
    out = ManeuverOut.model_validate(m)
    assert out.stop_loss == pytest.approx(395.0)
    assert out.take_profit == pytest.approx(435.0)


@pytest.mark.asyncio
async def test_latest_prices_overlays_resolved_quote_when_db_empty():
    db = AsyncMock()

    class _Result:
        def all(self):
            return []

    db.execute = AsyncMock(return_value=_Result())

    with patch(
        "app.services.market_data.client.get_latest_quote_resolved",
        new=AsyncMock(return_value={"price": 512.34}),
    ):
        prices = await pa.latest_prices(db, ["MSFT"])

    assert prices["MSFT"] == pytest.approx(512.34)


@pytest.mark.asyncio
async def test_latest_prices_overlays_live_when_db_bar_stale():
    """Equities with old OHLCV bars must fetch live quotes, not serve stale closes."""
    from datetime import timedelta

    db = AsyncMock()
    stale_ts = datetime.now(timezone.utc) - timedelta(hours=6)

    class _Result:
        def all(self):
            return [("MSFT", 400.0, stale_ts)]

    db.execute = AsyncMock(return_value=_Result())

    with patch(
        "app.services.market_data.client.get_latest_quote_resolved",
        new=AsyncMock(return_value={"price": 512.34}),
    ):
        prices = await pa.latest_prices(db, ["MSFT"])

    assert prices["MSFT"] == pytest.approx(512.34)
