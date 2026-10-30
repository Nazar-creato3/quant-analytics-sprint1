"""Portfolio construction (plan C): cap, optimizer, vol, TCM, cash, tax, sleeves."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.services.construction.caps import envelope
from app.services.construction.construct import construct_sleeve
from app.services.construction.optimizer import Constraints, NameSpec, optimize
from app.services.construction.rebalance import RebalancePolicy, calendar_due, plan as rebalance_plan
from app.services.construction.sleeve_nav import assert_isolated, isolate_users, split_account_nav
from app.services.construction.tax_lots import Lot, plan_close, plan_open, would_wash
from app.services.construction.tcm import filter_by_edge, kyle_impact_bps, quote
from app.services.construction.vol_budget import NameRisk, forecast_book_vol, scale_book_to_vol_target


def _names(n: int = 4, **extra) -> list[NameSpec]:
    return [
        NameSpec(
            symbol=f"N{i}",
            mu=0.02 - i * 0.002,
            vol=0.15 + i * 0.02,
            sector="tech" if i < 2 else "staples",
            adv_usd=5_000_000,
            conviction=0.8 - i * 0.1,
            **extra,
        )
        for i in range(n)
    ]


def test_envelope_settings_250_not_10k():
    env = envelope(250.0, 0.0)
    assert env.deploy_cap == 250.0
    assert env.per_name == pytest.approx(25.0)
    assert env.max_book == pytest.approx(200.0)
    assert env.cash_buffer_frac == pytest.approx(0.20)


def test_optimizer_modes_respect_name_sector_cash():
    specs = _names()
    cons = Constraints(name_cap=0.10, sector_cap=0.15, exposure_cap=0.80, cash_buffer=0.20)
    for mode in ("conviction", "inv_vol", "risk_parity", "mean_variance"):
        book = optimize(specs, mode=mode, cons=cons, deploy_cap=250)
        assert book.cash >= 0.20 - 1e-6
        assert sum(abs(w) for w in book.weights) <= 0.80 + 1e-6
        assert max(book.weights) <= 0.10 + 1e-6
        tech = book.weights[0] + book.weights[1]
        assert tech <= 0.15 + 1e-6


def test_optimizer_turnover_and_adv():
    specs = _names()
    prev = [0.10, 0.10, 0.10, 0.10]
    specs = [
        NameSpec(
            symbol=s.symbol,
            mu=s.mu,
            vol=s.vol,
            sector=s.sector,
            adv_usd=50.0,
            current_w=prev[i],
            conviction=s.conviction,
        )
        for i, s in enumerate(specs)
    ]
    cons = Constraints(turnover_cap=0.05, participation=0.10, name_cap=0.25, cash_buffer=0.20)
    book = optimize(specs, mode="conviction", cons=cons, deploy_cap=250)
    assert "turnover" in book.notes or book.turnover <= 0.05 + 1e-6
    assert any(n.startswith("adv:") for n in book.notes) or max(book.weights) * 250 <= 5.0 + 1e-6


def test_vol_budget_scales_book_not_just_atr():
    names = [
        NameRisk("A", 0.4, 100, 4, 0.40),
        NameRisk("B", 0.4, 50, 1, 0.40),
    ]
    w, vb = scale_book_to_vol_target([0.4, 0.4], names, equity_usd=10_000, target_ann=0.12)
    assert vb.forecast_ann > 0.12
    assert vb.scale < 1.0
    assert sum(w) < 0.8
    assert forecast_book_vol([0.5, 0.5], [0.2, 0.2], corr=1.0) == pytest.approx(0.2)


def test_tcm_rejects_when_edge_below_cost():
    q = quote("AAPL", notional_usd=10_000, adv_usd=1_000_000, edge_return=0.0001)
    assert q.accept is False
    assert q.reason == "edge_lt_cost"
    assert q.net_edge < 0
    q2 = quote("AAPL", notional_usd=100, adv_usd=1_000_000, edge_return=0.01)
    assert q2.accept is True
    assert kyle_impact_bps(100_000, 1_000_000) > kyle_impact_bps(1_000, 1_000_000)
    flags, _ = filter_by_edge(["A", "B"], edges=[0.00001, 0.05], notionals=[5000, 5000], adv=[1e6, 1e6])
    assert flags == [False, True]


def test_rebalance_calendar_and_drift_and_cash():
    pol = RebalancePolicy(calendar="weekly", weekday=0, drift_band=0.20, cash_buffer=0.20)
    assert calendar_due(None, date(2026, 9, 21), pol) is True
    assert calendar_due(date(2026, 9, 14), date(2026, 9, 21), pol) is True  # Monday
    assert calendar_due(date(2026, 9, 21), date(2026, 9, 22), pol) is False
    dec = rebalance_plan(
        ["A", "B"],
        [0.10, 0.10],
        [0.40, 0.40],
        as_of=date(2026, 9, 22),
        last=date(2026, 9, 21),
        policy=pol,
    )
    assert dec.due is True
    assert "drift" in dec.reason
    assert dec.cash_after >= 0.20 - 1e-6


def test_wash_sale_paper_fifo():
    lots = [
        Lot("1", "AAPL", 10, 100, date(2026, 8, 1), "paper", "retail_long_only", True),
        Lot("2", "AAPL", 5, 110, date(2026, 9, 1), "paper", "retail_long_only", True),
    ]
    close = plan_close(
        lots, symbol="AAPL", qty=12, as_of=date(2026, 9, 21),
        account="paper", sleeve_id="retail_long_only", sale_is_loss=True,
        pending_buy=date(2026, 9, 25),
    )
    assert close.wash_blocked is True
    fifo = plan_close(
        lots, symbol="AAPL", qty=12, as_of=date(2026, 9, 21),
        account="paper", sleeve_id="retail_long_only", sale_is_loss=False,
    )
    assert fifo.lots[0] == ("1", 10.0)
    assert fifo.lots[1][0] == "2"
    ok, why = plan_open(
        symbol="AAPL",
        as_of=date(2026, 9, 21),
        account="paper",
        sleeve_id="retail_long_only",
        recent_loss_sales=[("AAPL", date(2026, 9, 10), "paper", "retail_long_only")],
    )
    assert ok is False and why == "wash_sale_blocked"
    assert would_wash(
        symbol="AAPL", account="paper", sleeve_id="retail_long_only",
        loss_sale_on=date(2026, 9, 1), replacement_buy_on=date(2026, 9, 20), taxable=True,
    )


def test_sleeve_nav_isolation():
    paper = split_account_nav(user_id="u1", account="paper", nav=1000, deploy_cap=250)
    live = split_account_nav(user_id="u1", account="live", nav=5000, deploy_cap=250)
    assert assert_isolated(paper[0], live[0]) is True
    assert sum(s.nav for s in paper) == pytest.approx(1000)
    assert sum(s.deploy_cap for s in paper if s.sleeve != "cash") <= 250 + 1e-6
    other = split_account_nav(user_id="u2", account="paper", nav=1000, deploy_cap=250)
    grouped = isolate_users([*paper, *live, *other])
    assert ("u1", "paper") in grouped
    assert ("u1", "live") in grouped
    assert ("u2", "paper") in grouped


def test_construct_cap_250_never_800():
    rows = [
        {"symbol": "AAA", "p_beat_21": 0.80, "score_21": 8, "vol": 0.2, "price": 10, "atr": 0.3, "adv_usd": 1e6, "sector": "tech"},
        {"symbol": "BBB", "p_beat_21": 0.55, "score_21": 6, "vol": 0.2, "price": 10, "atr": 0.3, "adv_usd": 1e6, "sector": "tech"},
        {"symbol": "CCC", "p_beat_21": 0.70, "score_21": 7, "vol": 0.25, "price": 20, "atr": 0.5, "adv_usd": 1e6, "sector": "staples"},
    ]
    book = construct_sleeve(rows, settings_cap=250, account_total=0, user_id="u1", account="paper")
    assert book["deploy_cap"] == 250.0
    assert book["book_usd"] <= 200.0 + 1e-6
    assert book["cash_usd"] >= 50.0 - 1e-6
    assert all(h["notional_usd"] <= 25.0 + 1e-6 for h in book["holdings"])
    assert book["book_usd"] < 400  # never the $800 class


def test_construct_wash_blocks_replacement_buy():
    rows = [{"symbol": "AAPL", "p_beat_21": 0.80, "vol": 0.2, "price": 100, "atr": 2, "adv_usd": 1e7}]
    book = construct_sleeve(
        rows,
        settings_cap=250,
        recent_loss_sales=[("AAPL", date(2026, 9, 10), "paper", "retail_long_only")],
        as_of=date(2026, 9, 21),
        account="paper",
        sleeve="retail_long_only",
    )
    assert any("wash" in r for r in book["rejected"])
    assert book["holdings"] == []


def test_daily_book_includes_construction():
    from app.services.forecast.daily_book import build_daily_book

    rows = [{"symbol": f"N{i}", "score_21": 8, "p_beat_21": 0.7} for i in range(4)]
    book = build_daily_book(rows, retail_cap_usd=250)
    assert book["construction"] is not None
    assert book["construction"]["deploy_cap"] == 250.0


def test_tcm_reject_leaves_cash_not_redistributed():
    """Cycle 2: dead name stays cash — no 1/n dump into the survivor."""
    rows = [
        {"symbol": "EDGE", "p_beat_21": 0.90, "vol": 0.15, "price": 10, "atr": 0.2, "adv_usd": 1e7, "sector": "tech"},
        {"symbol": "COSTLY", "p_beat_21": 0.501, "vol": 0.15, "price": 10, "atr": 0.2, "adv_usd": 1e7, "sector": "staples"},
    ]
    book = construct_sleeve(rows, settings_cap=250, account_total=250)
    rejected_syms = {r.split(":")[0] for r in book["rejected"]}
    assert "COSTLY" in rejected_syms
    held = {h["symbol"] for h in book["holdings"]}
    assert "COSTLY" not in held
    assert book["cash_usd"] >= 50.0 - 1e-6
    if "EDGE" in held:
        assert all(h["notional_usd"] <= 25.0 + 1e-6 for h in book["holdings"])


def test_monthly_calendar_and_inside_band():
    """Cycle 3: monthly calendar + no-trade inside drift band."""
    pol = RebalancePolicy(calendar="monthly", drift_band=0.50, cash_buffer=0.20)
    assert calendar_due(date(2026, 8, 31), date(2026, 9, 1), pol) is True
    assert calendar_due(date(2026, 9, 1), date(2026, 9, 15), pol) is False
    dec = rebalance_plan(
        ["A"],
        [0.40],
        [0.41],
        as_of=date(2026, 9, 15),
        last=date(2026, 9, 1),
        policy=pol,
    )
    assert dec.due is False
    assert dec.reason == "inside_band"


def test_construct_paper_live_sleeves_never_net():
    """Cycle 4: same user paper vs live sleeves stay isolated."""
    rows = [{"symbol": "AAA", "p_beat_21": 0.8, "vol": 0.2, "price": 10, "atr": 0.3, "adv_usd": 1e6}]
    paper = construct_sleeve(rows, settings_cap=250, account_total=1000, user_id="u1", account="paper")
    live = construct_sleeve(rows, settings_cap=250, account_total=5000, user_id="u1", account="live")
    p0 = paper["sleeves"][0]
    l0 = live["sleeves"][0]
    assert p0["account"] != l0["account"]
    assert p0["user_id"] == l0["user_id"]
    assert paper["deploy_cap"] == 250.0
    assert live["deploy_cap"] == 250.0


def test_empty_score_book_still_has_cap_envelope():
    """Cycle 6: no names past the score gate → cash book, still operator cap."""
    from app.services.forecast.daily_book import build_daily_book

    book = build_daily_book([{"symbol": "AAPL", "score_20": 5, "p_beat_20": 0.55}], retail_cap_usd=250)
    assert book["count"] == 0
    assert book["construction"] is not None
    assert book["construction"]["deploy_cap"] == 250.0
    assert book["construction"]["holdings"] == []
    assert book["construction"]["cash_usd"] == 250.0


def test_wash_sale_does_not_cross_sleeves():
    """Cycle 6b: loss in CS sleeve does not block retail open (lot isolation)."""
    ok, why = plan_open(
        symbol="AAPL",
        as_of=date(2026, 9, 21),
        account="paper",
        sleeve_id="retail_long_only",
        recent_loss_sales=[("AAPL", date(2026, 9, 10), "paper", "cross_sectional")],
    )
    assert ok is True and why == "ok"


def test_optimizer_name_cap_after_adv_clip():
    """Cycle 5: ADV clip then name/cash still bind; leftover is cash."""
    specs = [
        NameSpec("ILLIQ", mu=0.05, vol=0.2, sector="tech", adv_usd=80.0, conviction=1.0),
        NameSpec("LIQ", mu=0.04, vol=0.2, sector="staples", adv_usd=5_000_000, conviction=0.5),
    ]
    cons = Constraints(name_cap=0.10, sector_cap=0.30, participation=0.10, cash_buffer=0.20, exposure_cap=0.80)
    book = optimize(specs, mode="conviction", cons=cons, deploy_cap=250)
    assert book.weights[0] <= (80.0 * 0.10) / 250.0 + 1e-8
    assert max(book.weights) <= 0.10 + 1e-8
    assert book.cash >= 0.20 - 1e-6


def test_risk_model_lw_factor_bayes_psd():
    rng = np.random.default_rng(0)
    hist = {f"N{i}": rng.normal(0, 0.01, 80).tolist() for i in range(4)}
    from app.services.construction.risk_model import blend_cov

    rb = blend_cov(
        ["N0", "N1", "N2", "N3"],
        [0.2] * 4,
        hist=hist,
        sectors=["tech", "tech", "staples", "staples"],
        size=[1, 2, 3, 4],
    )
    eig = np.linalg.eigvalsh(rb.cov)
    assert float(eig.min()) > -1e-8
    assert "factor_bfb_d" in rb.notes
    assert rb.idio_var.size == 4


def test_te_cap_shrinks_active_risk():
    specs = _names(3)
    hist = {s.symbol: [0.01, -0.01] * 20 for s in specs}
    cons = Constraints(name_cap=0.25, sector_cap=0.50, cash_buffer=0.20, te_cap=0.01, te_aversion=20.0)
    bench = [0.2, 0.2, 0.2]
    book = optimize(specs, mode="mean_variance", hist=hist, cons=cons, deploy_cap=250, bench_weights=bench)
    assert book.te <= 0.01 + 1e-3 or "te_cap" in book.notes


def test_restricted_and_country_compliance():
    rows = [
        {"symbol": "BAD", "p_beat_21": 0.9, "vol": 0.2, "adv_usd": 1e7, "country": "US"},
        {"symbol": "OK", "p_beat_21": 0.8, "vol": 0.2, "adv_usd": 1e7, "country": "US"},
        {"symbol": "CNY", "p_beat_21": 0.85, "vol": 0.2, "adv_usd": 1e7, "country": "CN"},
    ]
    book = construct_sleeve(
        rows, settings_cap=250, account_total=250, restricted=["BAD"], blocked_countries=["CN"]
    )
    held = {h["symbol"] for h in book["holdings"]}
    assert "BAD" not in held
    assert "CNY" not in held
    assert any(r.startswith("BAD:") for r in book["rejected"])


def test_hifo_min_tax_specific_id():
    from app.services.construction.lot_store import apply_split, pick_lots

    lots = [
        Lot("lo", "AAPL", 10, 80, date(2026, 1, 1), "paper", "retail_long_only", True),
        Lot("hi", "AAPL", 10, 120, date(2026, 2, 1), "paper", "retail_long_only", True),
    ]
    hifo = pick_lots(lots, symbol="AAPL", account="paper", sleeve_id="retail_long_only", qty=10, method="hifo")
    assert hifo[0].lot_id == "hi"
    mint = pick_lots(
        lots, symbol="AAPL", account="paper", sleeve_id="retail_long_only", qty=10,
        method="min_tax", sale_price=100,
    )
    assert mint[0].lot_id == "hi"  # loss vs 120 first
    spec = pick_lots(
        lots, symbol="AAPL", account="paper", sleeve_id="retail_long_only", qty=10,
        method="specific_id", specific_ids=["lo"],
    )
    assert spec[0].lot_id == "lo"
    split = apply_split(lots, symbol="AAPL", ratio=2.0)
    assert split[0].qty == 20 and split[0].cost == pytest.approx(40)


def test_tplus_pending_then_settled_and_div_nav():
    from app.services.construction.sleeve_nav import (
        apply_ca_to_nav,
        new_trade_leg,
        pending_cash,
        settled_cash,
        t_plus,
    )

    as_of = date(2026, 9, 21)  # Monday
    settle = t_plus(as_of, 1)
    assert settle == date(2026, 9, 22)
    leg = new_trade_leg(
        amount=-25.0, as_of=as_of, kind="buy_debit", user_id="u1", account="paper", sleeve="retail_long_only"
    )
    assert pending_cash([leg], as_of=as_of, user_id="u1", account="paper", sleeve="retail_long_only") == -25.0
    assert settled_cash([leg], as_of=as_of, user_id="u1", account="paper", sleeve="retail_long_only") == 0.0
    assert settled_cash([leg], as_of=settle, user_id="u1", account="paper", sleeve="retail_long_only") == -25.0
    assert pending_cash([leg], as_of=settle, user_id="u1", account="live", sleeve="retail_long_only") == 0.0
    assert apply_ca_to_nav(1000.0, cash_dividend_usd=12.5, split_ratio=2.0) == 1012.5


def test_allocate_book_of_record_still_caps_250():
    from app.core.config import settings
    from app.services.risk.maneuver_generator import ManeuverOutput
    from app.services.risk.portfolio_sizing import allocate_deploy_budget

    def _m(ticker: str, conf: float) -> ManeuverOutput:
        return ManeuverOutput(
            rank=1,
            ticker=ticker,
            strategy_type="momentum",
            direction="long",
            entry_zone_low=100.0,
            entry_zone_high=101.0,
            exit_zone_low=110.0,
            exit_zone_high=111.0,
            stop_loss=95.0,
            take_profit=110.0,
            invalidation_level=94.0,
            risk_percent=2.0,
            position_size_usd=800.0,
            expected_return_low=3.0,
            expected_return_high=6.0,
            expected_pnl_low=12.0,
            expected_pnl_high=24.0,
            confidence=conf,
            time_horizon="1–5 days",
            catalyst="test",
            rationale="test",
            execution_plan="Размер: $800.",
        )

    outs = allocate_deploy_budget([_m("AAA", 0.90), _m("BBB", 0.12)], 250.0)
    tradeable = [m for m in outs if not m.is_no_trade]
    per_name = 250.0 * settings.MAX_POSITION_PCT / 100
    max_book = 250.0 * settings.MAX_PORTFOLIO_EXPOSURE_PCT / 100
    assert tradeable
    for m in tradeable:
        assert m.position_size_usd <= per_name + 1e-6
        assert abs(m.position_size_usd - 800.0) > 100
    assert sum(m.position_size_usd for m in tradeable) <= max_book + 1e-6
