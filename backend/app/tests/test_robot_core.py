"""Robot Core P0: plan levels + FIFO lot math (pure / mocked)."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import SignalDirection
from app.services.robot.plan import build_levels_from_maneuver


def _maneuver(**kwargs):
    base = dict(
        direction=SignalDirection.LONG,
        fill_price=100.0,
        entry_zone_low=95.0,
        entry_zone_high=102.0,
        stop_loss=90.0,
        take_profit=120.0,
        filled_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        signal_meta={},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_build_levels_long_has_entry_add_tp_sl_trail():
    levels = build_levels_from_maneuver(_maneuver())
    kinds = [lv["kind"] for lv in levels]
    assert kinds == ["entry", "add", "tp", "sl", "trail"]
    entry = levels[0]
    assert entry["status"] == "filled"
    assert entry["price"] == 100.0
    add = levels[1]
    assert add["kind"] == "add"
    assert add["price"] == 97.5  # midpoint entry↔zone_lo
    assert add["status"] == "watching"
    tp = next(lv for lv in levels if lv["kind"] == "tp")
    assert tp["price"] == 120.0
    assert tp["size_pct"] == 50.0
    assert tp["id"] == "tp_1"
    assert next(lv for lv in levels if lv["kind"] == "sl")["price"] == 90.0
    trail = next(lv for lv in levels if lv["kind"] == "trail")
    assert trail["status"] == "pending"
    assert trail["size_pct"] == 50.0


def test_trail_ratchets_and_hits_long():
    from app.services.robot.monitor import _update_trail_level

    lv = {
        "kind": "trail",
        "status": "pending",
        "activate_at": 120.0,
        "trail_pct": 1.5,
        "peak_price": None,
        "price": None,
    }
    assert _update_trail_level(lv, high=119.0, low=118.0, close=118.5, side_book="long") is False
    assert lv["status"] == "pending"
    # Arm on pierce — no fill same bar
    assert _update_trail_level(lv, high=121.0, low=120.0, close=120.5, side_book="long") is False
    assert lv["status"] == "armed"
    assert lv["peak_price"] == 121.0
    stop1 = 121.0 * (1 - 0.015)
    assert lv["price"] == pytest.approx(stop1, rel=1e-6)
    # Ratchet higher without false hit on wide bar
    assert _update_trail_level(lv, high=130.0, low=125.0, close=128.0, side_book="long") is False
    assert lv["peak_price"] == 130.0
    stop2 = 130.0 * (1 - 0.015)
    assert lv["price"] == pytest.approx(stop2, rel=1e-6)
    # Next bar pierces prior stop
    assert _update_trail_level(lv, high=129.0, low=stop2 - 0.01, close=stop2, side_book="long") is True


def test_build_levels_short_add_above_entry():
    levels = build_levels_from_maneuver(
        _maneuver(
            direction=SignalDirection.SHORT,
            fill_price=100.0,
            entry_zone_low=98.0,
            entry_zone_high=108.0,
            stop_loss=110.0,
            take_profit=85.0,
        )
    )
    add = next(lv for lv in levels if lv["kind"] == "add")
    assert add["side"] == "sell"
    assert add["price"] == 104.0


def test_level_hit_long_add_on_dip():
    from app.services.robot.monitor import _level_hit

    lv = {"kind": "add", "price": 97.5, "status": "watching"}
    assert _level_hit(lv, high=99.0, low=97.0, side_book="long") is True
    assert _level_hit(lv, high=99.0, low=98.0, side_book="long") is False


def test_level_hit_long_tp_sl():
    from app.services.robot.monitor import _level_hit

    tp = {"kind": "tp", "price": 120.0, "status": "watching"}
    sl = {"kind": "sl", "price": 90.0, "status": "watching"}
    assert _level_hit(tp, high=121.0, low=119.0, side_book="long") is True
    assert _level_hit(sl, high=91.0, low=89.5, side_book="long") is True


def test_kind_priority_risk_first():
    from app.services.robot.monitor import _kind_priority

    assert _kind_priority("sl") < _kind_priority("tp") < _kind_priority("add")


def test_cancel_open_levels_keeps_filled():
    from app.services.robot.monitor import _cancel_open_levels

    levels = [
        {"id": "sl", "status": "filled"},
        {"id": "tp", "status": "watching"},
        {"id": "add_1", "status": "watching"},
    ]
    _cancel_open_levels(levels, except_id="sl")
    assert levels[0]["status"] == "filled"
    assert levels[1]["status"] == "cancelled"
    assert levels[2]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_book_snapshot_avg_vwap():
    from app.services.portfolio.lot_ledger import book_snapshot

    lots = [
        SimpleNamespace(
            id="a",
            side="long",
            qty_open=2.0,
            qty_initial=2.0,
            entry_price=100.0,
            fee_usd=0.2,
            opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            maneuver_id="m1",
            source="maneuver",
        ),
        SimpleNamespace(
            id="b",
            side="long",
            qty_open=1.0,
            qty_initial=1.0,
            entry_price=106.0,
            fee_usd=0.1,
            opened_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            maneuver_id="m2",
            source="robot_add",
        ),
    ]
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = lots
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)

    with patch("app.services.portfolio.lot_ledger.settings") as settings:
        settings.COMMISSION_RATE_PCT = 0.0
        snap = await book_snapshot(db, user_id="u1", ticker="BTC")

    assert snap.side == "long"
    assert snap.qty == 3.0
    assert snap.avg_entry == pytest.approx((200.0 + 106.0) / 3.0, rel=1e-6)
    assert snap.open_lots == 2


@pytest.mark.asyncio
async def test_reduce_lots_fifo_realized():
    from app.services.portfolio.lot_ledger import reduce_lots_fifo

    lot = MagicMock()
    lot.id = "lot-1"
    lot.ticker = "ETH"
    lot.side = "long"
    lot.qty_open = 10.0
    lot.qty_initial = 10.0
    lot.entry_price = 100.0
    lot.fee_usd = 0.0
    lot.status = "open"
    lot.closed_at = None

    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = [lot]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch("app.services.portfolio.lot_ledger.settings") as settings:
        settings.COMMISSION_RATE_PCT = 0.0
        out = await reduce_lots_fifo(
            db,
            user_id="u1",
            ticker="ETH",
            side="long",
            qty=4.0,
            exit_price=110.0,
            reason="tp",
        )

    assert out["closed_qty"] == 4.0
    assert out["realized_pnl"] == pytest.approx(40.0)
    assert lot.qty_open == 6.0
    assert lot.status == "open"
    assert db.add.called


def test_freqtrade_roi_ladder_to_levels():
    from app.services.robot.freqtrade_bridge import levels_from_freqtrade_params

    levels = levels_from_freqtrade_params(
        entry=100.0,
        side="long",
        minimal_roi={"0": 0.04, "60": 0.02},
        stoploss=-0.08,
        trailing_stop=True,
        trailing_stop_positive=0.015,
    )
    kinds = [lv["kind"] for lv in levels]
    assert "entry" in kinds and "tp" in kinds and "sl" in kinds and "trail" in kinds
    tps = [lv for lv in levels if lv["kind"] == "tp"]
    assert len(tps) == 2
    assert tps[0]["price"] == pytest.approx(104.0)  # highest ROI first
    assert tps[1]["price"] == pytest.approx(102.0)
    sl = next(lv for lv in levels if lv["kind"] == "sl")
    assert sl["price"] == pytest.approx(92.0)
    assert sum(lv["size_pct"] for lv in tps) == pytest.approx(100.0)


def test_apex_signal_bridge_defaults():
    from app.services.robot.freqtrade_bridge import levels_from_apex_signal_bridge

    levels = levels_from_apex_signal_bridge(entry=50.0, side="long")
    sl = next(lv for lv in levels if lv["kind"] == "sl")
    assert sl["price"] == pytest.approx(50.0 * 0.92)
    assert any(lv["kind"] == "trail" for lv in levels)


def test_kill_switch_drawdown_pct():
    from app.services.robot.risk import drawdown_pct

    assert drawdown_pct(peak=100.0, equity=95.0) == pytest.approx(5.0)
    assert drawdown_pct(peak=100.0, equity=105.0) == 0.0
    assert drawdown_pct(peak=0.0, equity=10.0) == 0.0


def test_live_brackets_from_levels():
    from app.services.robot.live_sync import brackets_from_levels

    br = brackets_from_levels(
        [
            {"kind": "tp", "price": 120.0, "status": "watching"},
            {"kind": "tp", "price": 130.0, "status": "watching"},
            {"kind": "sl", "price": 90.0, "status": "watching"},
            {"kind": "trail", "price": 95.0, "status": "armed"},
        ]
    )
    assert br["take_profit"] == 120.0
    assert br["stop_loss"] == 90.0


def test_shadow_hits_sl():
    from app.services.robot.shadow import run_robot_shadow

    levels = [
        {"id": "entry", "kind": "entry", "price": 100.0, "status": "filled"},
        {"id": "sl", "kind": "sl", "price": 95.0, "size_pct": 100.0, "status": "watching"},
        {"id": "tp_1", "kind": "tp", "price": 110.0, "size_pct": 50.0, "status": "watching"},
    ]
    bars = [
        {"high": 101.0, "low": 99.0, "close": 100.5},
        {"high": 100.0, "low": 94.5, "close": 95.0},
    ]
    out = run_robot_shadow(bars, levels=levels, side="long", qty=10.0, kill_switch_pct=None)
    assert out.exit_reason == "stop"
    assert out.final_qty == 0.0
    assert any(f.kind == "sl" for f in out.fills)
    assert out.realized_pnl == pytest.approx(-50.0)


def test_shadow_partial_tp_then_trail():
    from app.services.robot.freqtrade_bridge import levels_from_freqtrade_params
    from app.services.robot.shadow import run_robot_shadow

    levels = levels_from_freqtrade_params(
        entry=100.0,
        side="long",
        minimal_roi={"0": 0.10},
        stoploss=-0.20,
        trailing_stop=True,
        trailing_stop_positive=0.02,
        add_zone_pct=None,
    )
    # Climb to TP (+10%), then pull back through trail
    bars = [
        {"high": 101.0, "low": 99.5, "close": 100.5},
        {"high": 111.0, "low": 109.0, "close": 110.0},  # TP hit → partial + arm trail
        {"high": 112.0, "low": 110.5, "close": 111.0},  # ratchet
        {"high": 111.0, "low": 107.0, "close": 108.0},  # may hit trail vs prior stop
    ]
    out = run_robot_shadow(bars, levels=levels, side="long", qty=2.0, kill_switch_pct=None)
    kinds = [f.kind for f in out.fills]
    assert "entry" in kinds
    assert any(k.startswith("tp") for k in kinds)


def test_side_book_dual_and_funding_be():
    from datetime import datetime, timezone, timedelta
    from app.services.portfolio.lot_ledger import _side_book_from_lots

    opened = datetime.now(timezone.utc) - timedelta(days=10)
    long_lot = SimpleNamespace(
        qty_open=2.0,
        qty_initial=2.0,
        entry_price=100.0,
        fee_usd=0.2,
        opened_at=opened,
        meta={},
    )
    with patch("app.services.portfolio.lot_ledger.settings") as s:
        s.COMMISSION_RATE_PCT = 0.1
        s.FUNDING_RATE_PCT_PER_DAY = 0.01
        with patch("app.services.portfolio.cost_basis.settings", s):
            book = _side_book_from_lots([long_lot], side="long")
    assert book.avg_entry == 100.0
    assert book.funding_usd > 0
    assert book.breakeven is not None and book.breakeven > 100.0
