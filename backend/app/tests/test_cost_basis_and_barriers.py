"""Unit tests for Average Buy / markers and SL-TP barrier hits."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.db.models import ManeuverStatus, SignalDirection
from app.services.portfolio.barrier_close import barrier_hit, barrier_hit_range
from app.services.portfolio.cost_basis import (
    build_markers,
    entry_zone_range,
    fee_adjusted_breakeven,
    unrealized_vs_avg,
    weighted_avg_entry,
)


def _m(**kwargs):
    defaults = dict(
        id="m1",
        ticker="BTC-USD",
        direction=SignalDirection.SHORT,
        status=ManeuverStatus.FILLED,
        fill_price=78000.0,
        entry_price=78000.0,
        position_size_usd=7800.0,
        entry_zone_low=76000.0,
        entry_zone_high=79000.0,
        stop_loss=82000.0,
        take_profit=74000.0,
        exit_price=None,
        exit_reason=None,
        filled_at=None,
        approved_at=None,
        created_at=None,
        closed_at=None,
        signal_meta={},
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_weighted_avg_entry_two_legs():
    a = _m(fill_price=100.0, position_size_usd=1000.0)  # 10 qty
    b = _m(id="m2", fill_price=120.0, position_size_usd=1200.0)  # 10 qty
    assert weighted_avg_entry([a, b]) == 110.0


def test_entry_zone_excludes_barriers():
    m = _m(stop_loss=82000.0, take_profit=74000.0, entry_zone_low=76000.0, entry_zone_high=79000.0)
    lo, hi = entry_zone_range([m])
    assert lo == 76000.0
    assert hi == 79000.0


def test_fee_breakeven_long_and_short():
    with patch("app.services.portfolio.cost_basis.settings") as s:
        s.COMMISSION_RATE_PCT = 0.1  # 0.1% → 0.2% round-trip
        assert fee_adjusted_breakeven(100.0, side="long") == 100.2
        assert fee_adjusted_breakeven(100.0, side="short") == 99.8


def test_fee_breakeven_with_funding_and_qty():
    with patch("app.services.portfolio.cost_basis.settings") as s:
        s.COMMISSION_RATE_PCT = 0.1
        # qty=10, avg=100 → notional 1000; entry_fee 1 + exit_fee 1 + funding 2 = 4 → shift 0.4
        be = fee_adjusted_breakeven(
            100.0, side="long", qty=10.0, fee_usd=1.0, funding_usd=2.0
        )
        assert be == pytest.approx(100.4)
        be_s = fee_adjusted_breakeven(
            100.0, side="short", qty=10.0, fee_usd=1.0, funding_usd=2.0
        )
        assert be_s == pytest.approx(99.6)


def test_unrealized_short_profit_when_price_drops():
    pnl, pct = unrealized_vs_avg(100.0, 90.0, 2.0, side="short")
    assert pnl == 20.0
    assert pct == 10.0


def test_barrier_short_stop_and_tp():
    m = _m(direction=SignalDirection.SHORT, fill_price=78000, stop_loss=80000, take_profit=75000)
    assert barrier_hit(m, 80500) == "stop"
    assert barrier_hit(m, 74000) == "take_profit"
    assert barrier_hit(m, 77000) is None


def test_barrier_gap_prefers_stop():
    # Long gaps through both TP and SL in one print — stop wins.
    m = _m(direction=SignalDirection.LONG, fill_price=100, stop_loss=90, take_profit=110)
    assert barrier_hit(m, 80) == "stop"  # below SL (and would be past TP if inverted, but only SL)
    m2 = _m(direction=SignalDirection.LONG, fill_price=100, stop_loss=95, take_profit=90)
    # Weird inverted levels: price 88 hits both TP (<=90) wait long TP is price>=tp
    # For long: SL hit at price<=95, TP hit at price>=90 → at 88 only SL
    assert barrier_hit(m2, 88) == "stop"
    # Short gap both: SL=110 TP=90, price=120 hits SL; price=80 hits TP; price that hits both?
    m3 = _m(direction=SignalDirection.SHORT, fill_price=100, stop_loss=90, take_profit=110)
    # short: stop when price>=90, tp when price<=110 — almost always both at mid. At 100 both true → stop
    assert barrier_hit(m3, 100) == "stop"


def test_barrier_long_stop_and_tp():
    m = _m(direction=SignalDirection.LONG, fill_price=100, stop_loss=90, take_profit=120)
    assert barrier_hit(m, 89) == "stop"
    assert barrier_hit(m, 121) == "take_profit"


def test_barrier_intra_bar_high_low_pierce():
    m = _m(direction=SignalDirection.LONG, fill_price=100, stop_loss=95, take_profit=110)
    # Close still inside, but low pierced SL
    assert barrier_hit_range(m, high=102, low=94, close=101) == "stop"
    # High pierced TP, close back
    assert barrier_hit_range(m, high=111, low=100, close=105) == "take_profit"
    # Both pierced in one bar → stop wins
    assert barrier_hit_range(m, high=112, low=93, close=100) == "stop"


def test_markers_entry_and_exit_labels():
    m = _m(
        status=ManeuverStatus.CLOSED,
        filled_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        closed_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        exit_price=75000.0,
        exit_reason="take_profit",
    )
    marks = build_markers([m])
    assert len(marks) == 2
    assert marks[0].kind == "entry" and marks[0].side == "sell"
    assert marks[1].kind == "exit" and marks[1].label and marks[1].label.startswith("TP")
