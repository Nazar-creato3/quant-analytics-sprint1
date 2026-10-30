"""Execution desk: SOR, Cartea schedule, brackets, paper/live parity."""
from __future__ import annotations

import pytest

from app.services.execution.bracket_risk import align_with_engine, geometry_ok
from app.services.execution.desk import plan_execution
from app.services.execution.parity import nightly_parity
from app.services.execution.schedule import MAX_DAY_PARTICIPATION, MIN_SLICE_SECONDS, build_schedule
from app.services.execution.scorecard import build_scorecards
from app.services.execution.sor import eligible_venues, pick_venue


def _fill(venue: str, arrival: float, fill: float, side: str = "buy", status: str = "filled") -> dict:
    return {
        "venue": venue,
        "arrival_price": arrival,
        "fill_price": fill,
        "side": side,
        "status": status,
    }


def test_scorecard_prefers_tighter_is():
    fills = [_fill("alpaca", 100, 100.05) for _ in range(5)] + [_fill("paper", 100, 100.40) for _ in range(5)]
    cards = build_scorecards(fills)
    assert cards["alpaca"].n == 5
    assert cards["alpaca"].mean_is_bps < cards["paper"].mean_is_bps
    assert cards["alpaca"].score > cards["paper"].score


def test_sor_moex_stays_tinkoff_or_paper():
    elig = eligible_venues("SBER", keyed=["alpaca", "paper"])
    assert "tinkoff" not in elig
    assert "paper" in elig
    pick = pick_venue("SBER", keyed=["tinkoff", "alpaca"], paper_ok=True)
    assert pick.venue == "tinkoff"


def test_sor_us_picks_better_scorecard():
    fills = [_fill("alpaca", 100, 100.50) for _ in range(6)] + [_fill("tokenized_equity", 100, 100.05) for _ in range(6)]
    pick = pick_venue("AAPL", keyed=["alpaca", "tokenized_equity", "paper"], fills=fills)
    assert pick.venue == "tokenized_equity"


def test_twap_cartea_participation_and_wide_spread():
    sched = build_schedule(1000, adv_qty=5000, n_slices=5, horizon_minutes=10, kind="twap")
    assert sched.clipped_qty <= 5000 * MAX_DAY_PARTICIPATION + 1e-9
    assert sched.children
    assert sched.children[0].wait_seconds >= MIN_SLICE_SECONDS
    blocked = build_schedule(
        100, adv_qty=10_000, bid=100, ask=102, direction="long",  # 2% spread > 0.4%
    )
    assert blocked.clipped_qty == 0
    assert blocked.notes == ("wide_spread",)
    vwap = build_schedule(90, adv_qty=10_000, n_slices=3, kind="vwap", volume_profile=[1, 2, 6])
    assert vwap.children[2].qty > vwap.children[0].qty


def test_bracket_snaps_inverted_long_to_engine():
    chk = align_with_engine(
        ticker="AAPL",
        side="buy",
        entry=100,
        atr=2.0,
        stop_loss=110,  # inverted
        take_profit=90,
        portfolio_size=250,
    )
    assert chk.ok is True
    assert chk.stop_loss < 100 < chk.take_profit
    assert "snapped_to_engine" in chk.reasons or "geometry_fix" in chk.reasons
    assert geometry_ok(side="long", entry=100, sl=110, tp=90) == ["long_order"]


def test_live_sync_aligns_when_risk_context_given():
    from app.services.robot.live_sync import brackets_from_levels

    raw = brackets_from_levels(
        [{"kind": "sl", "price": 90.0, "status": "watching"}, {"kind": "tp", "price": 120.0, "status": "watching"}]
    )
    assert raw["stop_loss"] == 90.0
    aligned = brackets_from_levels(
        [{"kind": "sl", "price": 110.0, "status": "watching"}, {"kind": "tp", "price": 80.0, "status": "watching"}],
        entry=100.0,
        atr=2.0,
        side="long",
        portfolio_size=250.0,
    )
    assert aligned["stop_loss"] < 100 < aligned["take_profit"]
    assert aligned.get("bracket_ok") is True


def test_parity_flags_optimistic_paper():
    fills = [_fill("paper", 100, 100.01) for _ in range(8)] + [_fill("alpaca", 100, 100.30) for _ in range(8)]
    rep = nightly_parity(fills, max_optimistic_bps=8.0)
    assert rep.ok is False
    assert "paper_optimistic_is" in rep.reasons
    thin = nightly_parity([_fill("paper", 100, 100.01)])
    assert thin.ok is False
    assert "нет данных" in thin.reasons
    assert thin.live_fill == 0.0


def test_fill_tape_and_nightly_reads_it(tmp_path, monkeypatch):
    from app.services.execution.fill_tape import append_fill, load_fills
    from app.tasks.execution import nightly_paper_live_parity_task

    dest = tmp_path / "fills.jsonl"
    monkeypatch.setattr("app.services.execution.fill_tape.tape_path", lambda: dest)
    for _ in range(4):
        append_fill(_fill("paper", 100, 100.02), dest=dest)
        append_fill(_fill("alpaca", 100, 100.25), dest=dest)
    assert len(load_fills(dest=dest)) == 8
    report = nightly_paper_live_parity_task(fills=load_fills(dest=dest))
    assert report["ok"] is False
    assert "paper_optimistic_is" in report["reasons"]


def test_prepare_clips_parent_on_adv(monkeypatch):
    from app.services.execution.adapter import ManualOrderExecutionContext, OrderRequest
    from app.services.execution.runtime import prepare_request

    req = OrderRequest(
        ticker="AAPL",
        side="buy",
        qty=500,
        order_type="market",
        limit_price=100,
        manual_order_context=ManualOrderExecutionContext(manual_order_id="m1"),
    )
    new, meta = prepare_request(req, adv_qty=1000)
    assert new.qty <= 100 + 1e-9  # 10% ADV
    assert meta["schedule"]["clipped_qty"] == new.qty


def test_plan_execution_allow_and_leftover_not_hft():
    plan = plan_execution(
        ticker="AAPL",
        side="buy",
        qty=200,
        entry=100,
        atr=2,
        keyed_venues=["alpaca", "paper"],
        fills=[_fill("alpaca", 100, 100.04) for _ in range(4)],
        adv_qty=1000,
        stop_loss=96,
        take_profit=108,
        portfolio_size=250,
        kind="twap",
    )
    assert plan["venue"] in {"alpaca", "paper"}
    assert plan["schedule"]["children"]
    assert plan["schedule"]["children"][0]["wait_seconds"] >= 60
    assert plan["allow"] is True
    assert plan["bracket"]["ok"] is True
