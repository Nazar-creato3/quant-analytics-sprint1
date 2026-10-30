from __future__ import annotations

import asyncio
import json
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.market_data.indicators import ema_series, overlays_from_bars, sma_decimal, sma_series
from app.services.market_data.license import ISS_DELAY_LABEL, quote_envelope, stamp_quote
from app.services.market_data.quote_hub import QuoteHub
from app.services.market_data.series import Action, OhlcBar, adjust_ohlc

REPO = Path(__file__).resolve().parents[3]


def test_envelope_has_freshness_and_license():
    hidden = quote_envelope(
        symbol="SBER",
        price="100",
        source="iss_moex",
        as_of="2024-01-31",
        delayed=True,
        audience="public",
    )
    assert hidden["license_tag"] == "display_allowed"
    assert hidden["price"] == "100"
    assert hidden["freshness_label"] == ISS_DELAY_LABEL
    live = quote_envelope(
        symbol="BTC-USD",
        price="10",
        source="binance_public",
        as_of="2024-01-31",
        delayed=False,
        audience="owner",
    )
    assert live["freshness_label"] == "в реальном времени"
    delayed = quote_envelope(
        symbol="AAPL",
        price="1",
        source="yahoo",
        as_of="2024-01-31",
        delayed=True,
        delay_minutes=15,
        audience="internal",
    )
    assert delayed["freshness_label"] == "с задержкой 15 минут"
    assert delayed["price"] == "1"


def test_stamp_quote_hides_without_label_never():
    row = stamp_quote({"symbol": "SBER", "price": 250, "source": "iss_moex"}, audience="public")
    assert row["price"] == "250"
    assert row["freshness_label"] == ISS_DELAY_LABEL
    assert row["license_tag"] == "display_allowed"
    realtime = stamp_quote(
        {"symbol": "SBER", "price": 250, "source": "iss_moex", "delayed": False},
        audience="public",
    )
    assert realtime["price"] is None
    assert realtime["license_tag"] == "internal_only"


def test_indicator_goldens():
    golden = json.loads((REPO / "docs" / "qa" / "golden" / "indicators.json").read_text(encoding="utf-8"))
    sma = golden["sma_period_3"]
    got = sma_series(sma["closes"], 3)
    assert got == sma["values"]
    ema = golden["ema_period_3"]
    assert ema_series(ema["closes"], 3) == ema["values"]
    dec = sma_decimal([Decimal(str(x)) for x in sma["closes"]], 3)
    assert [None if v is None else float(v) for v in dec] == sma["values"]


def test_split_adj_candles_use_service_04():
    bars = [
        OhlcBar(date(2024, 1, 1), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100")),
        OhlcBar(date(2024, 1, 2), Decimal("10"), Decimal("11"), Decimal("9"), Decimal("10")),
    ]
    actions = [Action(date(2024, 1, 2), "split", factor=Decimal("10"))]
    adj = adjust_ohlc(bars, actions, "split_adj")
    assert adj[0].close == Decimal("10")
    assert adj[0].open == Decimal("10")
    # Split-day close follows get_series (factor applied on ex date).


def test_frontend_does_not_compute_sma():
    text = (REPO / "frontend" / "src" / "components" / "charts" / "movingAverages.ts").read_text(
        encoding="utf-8"
    )
    assert "function smaAt" not in text
    assert "sma_series" not in text
    assert "overlayFromAligned" in text


def test_indicator_perf_budget():
    budget = json.loads((REPO / "docs" / "qa" / "perf-budgets.json").read_text(encoding="utf-8"))
    spec = budget["indicators_ms"]
    closes = [float(i % 50) for i in range(int(spec["n"]))]
    bars = [{"close": c, "high": c + 1, "low": c - 1, "volume": 1} for c in closes]
    # Warm JIT/caches so a cold first call under CI load does not dominate.
    overlays_from_bars(bars[:200])
    samples = []
    for _ in range(3):
        t0 = time.perf_counter()
        overlays_from_bars(bars)
        samples.append((time.perf_counter() - t0) * 1000)
    elapsed_ms = min(samples)
    assert elapsed_ms < float(spec["max_ms"]), (elapsed_ms, samples)


@pytest.mark.asyncio
async def test_quote_hub_one_fetch_for_two_subscribers():
    hub = QuoteHub()
    n = {"c": 0}

    async def fetch(symbols: list[str]) -> dict:
        n["c"] += 1
        await asyncio.sleep(0.05)
        return {s: {"price": 1, "source": "binance_public"} for s in symbols}

    a, b = await asyncio.gather(
        hub.fetch_many(["BTC-USD"], fetch),
        hub.fetch_many(["BTC-USD"], fetch),
    )
    assert n["c"] == 1
    assert a["BTC-USD"]["price"] == 1
    assert b["BTC-USD"]["price"] == 1
    assert hub.fetch_counts["BTC-USD"] == 1
