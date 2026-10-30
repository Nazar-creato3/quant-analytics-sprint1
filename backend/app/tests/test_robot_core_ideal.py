"""Robot Core ideal — PositionCloser races, idempotency, caps, shadow friction, regime."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import ManeuverStatus
from app.services.robot.capabilities import (
    FeatureNotAvailableInLiveMode,
    assert_action_allowed,
    default_capabilities,
)
from app.services.robot.enricher import detect_regime, ensemble_signal
from app.services.robot.risk import drawdown_pct
from app.services.robot.shadow import run_robot_shadow


def test_capabilities_live_blocks_add():
    caps = default_capabilities("live")
    assert "entry" in caps["live"]
    assert "add" in caps["paper"]
    with pytest.raises(FeatureNotAvailableInLiveMode):
        assert_action_allowed(mode="live", action="add")
    assert_action_allowed(mode="paper", action="add")
    assert_action_allowed(mode="live", action="sl")


def test_shadow_slippage_recorded():
    levels = [
        {"id": "entry", "kind": "entry", "price": 100.0, "status": "filled"},
        {"id": "sl", "kind": "sl", "price": 95.0, "size_pct": 100.0, "status": "watching"},
    ]
    bars = [{"high": 101, "low": 94, "close": 94.5} for _ in range(5)]
    res = run_robot_shadow(
        bars,
        levels=levels,
        side="long",
        qty=1.0,
        slippage_pct=0.001,
        kill_switch_pct=None,
        seed=1,
    )
    assert res.avg_slippage == pytest.approx(0.001, rel=1e-6)
    assert any(f.kind == "sl" for f in res.fills)


def test_shadow_latency_delays_fill():
    levels = [
        {"id": "entry", "kind": "entry", "price": 100.0, "status": "filled"},
        {"id": "sl", "kind": "sl", "price": 95.0, "size_pct": 100.0, "status": "watching"},
    ]
    bars = [
        {"high": 101, "low": 94, "close": 96},
        {"high": 100, "low": 96, "close": 97},
        {"high": 99, "low": 96, "close": 97},
    ]
    res = run_robot_shadow(
        bars, levels=levels, side="long", qty=1.0, latency_bars=1, kill_switch_pct=None, seed=1
    )
    sl = next(f for f in res.fills if f.kind == "sl")
    assert sl.bar >= 1
    assert res.avg_latency_bars == pytest.approx(1.0)


def test_regime_trend_up():
    closes = [100 + i for i in range(30)]
    assert detect_regime(closes) == "trend_up"
    ens = ensemble_signal(closes)
    assert ens["regime"] == "trend_up"
    assert ens["signal"] != 0


def test_drawdown_pct():
    assert drawdown_pct(peak=100, equity=90) == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_three_concurrent_closes_only_one_wins():
    """Three closers serialized like FOR UPDATE — only one mutates FILLED→CLOSED."""
    import asyncio

    from app.services.robot.position_closer import close_maneuver_locked

    m = SimpleNamespace(
        id="m-race",
        status=ManeuverStatus.FILLED,
        exit_price=None,
        realized_pnl=None,
        ticker="BTC",
        direction="long",
        report=SimpleNamespace(created_by="u1"),
        fill_price=100.0,
        entry_price=100.0,
        position_size_usd=1000.0,
        signal_meta={},
    )
    lock = asyncio.Lock()

    class _Result:
        def scalar_one_or_none(self):
            return m

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())

    async def _one(reason: str, px: float):
        # Mimic row lock held for the duration of the close transaction
        async with lock:
            return await close_maneuver_locked(
                db, maneuver_id="m-race", user_id="u1", exit_price=px, reason=reason
            )

    with (
        patch("app.services.robot.position_closer.finalize_close_metadata", new_callable=AsyncMock),
        patch("app.services.robot.position_closer.close_maneuver_lots", new_callable=AsyncMock),
        patch("app.services.robot.position_closer.complete_plans_for_maneuver", new_callable=AsyncMock),
        patch("app.services.robot.position_closer.unrealized_net_pnl", return_value=5.0),
        patch("app.services.robot.reconcile.reconcile_maneuver_with_ledger", new_callable=AsyncMock),
    ):
        results = await asyncio.gather(
            _one("stop", 99.0),
            _one("take_profit", 101.0),
            _one("kill_switch", 100.0),
        )

    closed = sum(1 for r in results if r.closed)
    already = sum(1 for r in results if r.already_closed)
    assert closed == 1
    assert already == 2
    assert m.status == ManeuverStatus.CLOSED


def test_capabilities_matrix_complete():
    paper = default_capabilities("paper")
    live = default_capabilities("live")
    assert set(live["live"]) == {"entry", "sl", "tp"}
    assert "trail" in live["paper"] and "add" in live["paper"]
    assert "trail" in paper["paper"]


def test_grid_and_dca_level_builders():
    from app.services.robot.plan import levels_from_dca_params, levels_from_grid_params

    grid = levels_from_grid_params(entry=100.0, lower=90.0, upper=110.0, grid_count=5)
    assert grid[0]["kind"] == "entry"
    assert any(lv["kind"] == "add" for lv in grid)
    dca = levels_from_dca_params(entry=100.0, steps=3, step_pct=2.0)
    assert len([lv for lv in dca if lv["kind"] == "add"]) == 3
    assert dca[1]["price"] < 100.0


def test_shadow_equity_curve_length():
    levels = [
        {"id": "entry", "kind": "entry", "price": 100.0, "status": "filled"},
        {"id": "tp", "kind": "tp", "price": 110.0, "size_pct": 100.0, "status": "watching"},
    ]
    bars = [{"high": 100 + i * 0.5, "low": 99 + i * 0.4, "close": 100 + i * 0.45} for i in range(20)]
    res = run_robot_shadow(bars, levels=levels, side="long", qty=1.0, kill_switch_pct=None)
    assert len(res.equity) >= 1
    assert res.to_dict()["equity_curve"] == res.equity


@pytest.mark.asyncio
async def test_position_closer_second_call_already_closed():
    from app.services.robot.position_closer import close_maneuver_locked

    m = SimpleNamespace(
        id="m1",
        status=ManeuverStatus.FILLED,
        exit_price=None,
        realized_pnl=None,
        ticker="BTC",
        direction="long",
        report=SimpleNamespace(created_by="u1"),
        fill_price=100.0,
        entry_price=100.0,
        position_size_usd=1000.0,
        signal_meta={},
    )

    class _Result:
        def scalar_one_or_none(self):
            return m

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())

    with (
        patch("app.services.robot.position_closer.finalize_close_metadata", new_callable=AsyncMock),
        patch("app.services.robot.position_closer.close_maneuver_lots", new_callable=AsyncMock),
        patch("app.services.robot.position_closer.complete_plans_for_maneuver", new_callable=AsyncMock),
        patch("app.services.robot.position_closer.unrealized_net_pnl", return_value=10.0),
        patch("app.services.robot.reconcile.reconcile_maneuver_with_ledger", new_callable=AsyncMock),
    ):
        r1 = await close_maneuver_locked(
            db, maneuver_id="m1", user_id="u1", exit_price=110.0, reason="stop"
        )
        assert r1.closed is True
        assert m.status == ManeuverStatus.CLOSED
        r2 = await close_maneuver_locked(
            db, maneuver_id="m1", user_id="u1", exit_price=111.0, reason="take_profit"
        )
        assert r2.closed is False
        assert r2.already_closed is True


@pytest.mark.asyncio
async def test_claim_level_fill_idempotent():
    from app.services.robot.idempotency import claim_level_fill

    existing = SimpleNamespace(
        id="f1",
        plan_id="p1",
        level_id="add_1",
        action="add",
        celery_task_id="t1",
    )

    class _Res:
        def __init__(self, row):
            self._row = row

        def scalar_one_or_none(self):
            return self._row

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Res(existing))
    c2 = await claim_level_fill(
        db, plan_id="p1", level_id="add_1", action="add", celery_task_id="t1", qty=1, price=100
    )
    assert c2.claimed is False
    assert c2.fill is existing
    assert c2.idempotency_key == "p1:add_1:add:t1"


@pytest.mark.asyncio
async def test_reconcile_updates_size_from_ledger():
    from app.services.robot.reconcile import reconcile_maneuver_with_ledger
    from app.services.portfolio.lot_ledger import BookSnapshot

    m = SimpleNamespace(
        id="m1",
        ticker="ETH",
        direction="long",
        fill_price=100.0,
        entry_price=100.0,
        position_size_usd=500.0,
        signal_meta={},
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=m)
    snap = BookSnapshot(
        ticker="ETH",
        side="long",
        qty=2.0,
        avg_entry=100.0,
        cost_basis_usd=200.0,
        fee_usd=0.0,
        open_lots=1,
        breakeven=100.0,
        lots=[],
    )
    with patch(
        "app.services.robot.reconcile.book_snapshot", new_callable=AsyncMock, return_value=snap
    ):
        out = await reconcile_maneuver_with_ledger(db, maneuver_id="m1", user_id="u1")
    assert out["ok"] is True
    assert m.position_size_usd == pytest.approx(200.0)


def test_fee_adjusted_be_with_funding():
    from app.services.portfolio.cost_basis import fee_adjusted_breakeven

    # entry_fee + exit_fee(rate*notional) + funding → shift
    be = fee_adjusted_breakeven(100.0, side="long", qty=10.0, fee_usd=1.0, funding_usd=1.0)
    assert be > 100.0
    assert be == pytest.approx(100.3, abs=0.05)


def test_net_be_weighted():
    long_be, short_be = 1.23, 1.25
    long_q, short_q = 100.0, 50.0
    net = (long_be * long_q + short_be * short_q) / (long_q + short_q)
    assert net == pytest.approx(1.236666, rel=1e-4)


@pytest.mark.asyncio
async def test_exposure_limit_blocks():
    from app.services.robot.risk import ExposureLimitExceeded, check_exposure_limits

    state = SimpleNamespace(
        kill_switch_triggered=False,
        kill_switch_reason=None,
        max_exposure_symbol_pct=10.0,
        max_exposure_venue_pct=30.0,
        max_correlation=0.8,
    )
    snap = SimpleNamespace(cost_basis_usd=50.0)
    with (
        patch("app.services.robot.risk.get_or_create_risk_state", new_callable=AsyncMock, return_value=state),
        patch("app.services.robot.risk._user_portfolio_equity", new_callable=AsyncMock, return_value=100.0),
        patch("app.services.robot.risk.book_snapshot", new_callable=AsyncMock, return_value=snap),
    ):
        with pytest.raises(ExposureLimitExceeded):
            await check_exposure_limits(
                AsyncMock(), user_id="u1", symbol="BTC", add_notional=20.0
            )


@pytest.mark.asyncio
async def test_portfolio_kill_triggers():
    from app.services.robot.risk import check_portfolio_kill_switch

    state = SimpleNamespace(
        day_anchor_date=None,
        month_anchor=None,
        equity_start_of_day=100.0,
        equity_start_of_month=100.0,
        day_limit_pct=5.0,
        month_limit_pct=15.0,
        kill_switch_triggered=False,
        kill_switch_reason=None,
        updated_at=None,
    )
    with (
        patch("app.services.robot.risk.get_or_create_risk_state", new_callable=AsyncMock, return_value=state),
        patch("app.services.robot.risk._user_portfolio_equity", new_callable=AsyncMock, return_value=93.0),
    ):
        out = await check_portfolio_kill_switch(AsyncMock(), user_id="u1", flatten=False)
    assert out["triggered"] is True
    assert state.kill_switch_triggered is True
