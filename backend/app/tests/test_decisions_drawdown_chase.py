"""GA16-293: drawdown sales and chase buys from dated series, not stubs."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.decisions_report.service import _chase_buys, _drawdown_sales
from app.services.risk_engine.series import put_dated_prices, put_series, reset


def setup_function() -> None:
    reset()


def teardown_function() -> None:
    reset()


def _trade(ticker: str, qty: str, amount: str, day: date) -> SimpleNamespace:
    return SimpleNamespace(
        kind="trade",
        ticker=ticker,
        qty=Decimal(qty),
        amount=Decimal(amount),
        event_time=datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
    )


def test_drawdown_sale_detected() -> None:
    start = date(2024, 1, 2)
    imoex = []
    px = 100.0
    for i in range(70):
        d = start + timedelta(days=i)
        if i < 50:
            px = 100.0 + i * 0.1
        else:
            px = 100.0 * (0.85)  # >10% off peak
        imoex.append((d, px))
    put_dated_prices("IMOEX", imoex)
    sell_day = start + timedelta(days=60)
    out = _drawdown_sales([_trade("SBER", "-10", "900", sell_day)], thin=False)
    assert out["data_status"] == "ok"
    assert out["items"]
    assert out["items"][0]["ticker"] == "SBER"


def test_no_stub_when_undated_series_only() -> None:
    put_series("IMOEX", [0.01, -0.02, 0.0])
    out = _drawdown_sales([], thin=False)
    assert out["data_status"] == "нет данных"
    assert "дат" in (out.get("reason") or "")


def test_chase_buy_detected() -> None:
    start = date(2024, 1, 2)
    sber = []
    px = 100.0
    for i in range(40):
        d = start + timedelta(days=i)
        px = 100.0 * (1.0 + 0.012 * i)  # >20% over 20 sessions
        sber.append((d, px))
    put_dated_prices("SBER", sber)
    buy_day = start + timedelta(days=25)
    out = _chase_buys([_trade("SBER", "5", "600", buy_day)], thin=False)
    assert out["items"]
    assert Decimal(out["items"][0]["growth_20d"]) >= Decimal("0.20")
