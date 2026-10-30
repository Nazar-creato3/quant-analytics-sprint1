"""D. Risk / compliance / ops — free-data desk."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from app.services.ops_desk.disaster import backup_last_good, read_floor, seal_deploy_floor
from app.services.ops_desk.factors import factor_book, ff_loadings, herfindahl
from app.services.ops_desk.kills import evaluate_kills
from app.services.ops_desk.pretrade import check as pretrade_check, pdt_blocked, short_locate_proxy
from app.services.ops_desk.realtime import book_risk, parametric_var_es
from app.services.ops_desk.stress import run_all
from app.services.ops_desk.tca_post import one_fill_is, summarize_symbol


def test_parametric_and_hist_var():
    p95, p99, es = parametric_var_es(0.01)
    assert p99 > p95 > 0
    assert es >= p95
    rng = np.random.default_rng(1)
    hist = {"A": rng.normal(0, 0.01, 80).tolist(), "B": rng.normal(0, 0.01, 80).tolist()}
    br = book_risk([0.4, 0.4], ["A", "B"], hist=hist)
    assert br.n == 80
    assert br.var95_hist is not None and br.var95_hist >= 0
    assert br.var95_param > 0
    assert br.es95_hist is not None


def test_stress_2008_2020_rate():
    hits = run_all([0.5, 0.3], [1.2, 0.8], symbols=["AAA", "BBB"])
    names = {h.name for h in hits}
    assert names == {"gfc_2008", "covid_2020", "rate_spike"}
    gfc = next(h for h in hits if h.name == "gfc_2008")
    assert gfc.pnl_frac < 0
    assert gfc.worst_name in {"AAA", "BBB"}


def test_ff_and_concentration_and_spy_beta():
    w = [0.4, 0.4]
    assert herfindahl(w) == pytest.approx(0.5)
    rng = np.random.default_rng(2)
    mkt = rng.normal(0.0004, 0.01, 60)
    asset = 1.3 * mkt + rng.normal(0, 0.002, 60)
    spy = list(mkt)
    ff = [{"date": "x", "Mkt-RF": float(mkt[i]), "SMB": 0.0, "HML": 0.0} for i in range(60)]
    ld = ff_loadings(list(asset), ff)
    assert ld["mkt"] == pytest.approx(1.3, rel=0.25)
    fb = factor_book(
        w, ["A", "B"],
        sectors=["tech", "tech"],
        hist={"A": list(asset), "B": list(asset)},
        spy=spy,
        ff_rows=ff,
    )
    assert fb.max_sector == pytest.approx(0.8)
    assert fb.n_ff == 2
    assert "mkt" in fb.ff


def test_ga16_325_short_history_spy_beta_is_none():
    from app.services.ops_desk.factors import spy_beta

    assert spy_beta([0.01, 0.02], [0.01, 0.02]) is None
    assert spy_beta([0.01] * 5, [0.02] * 5) is None
    flat = [0.0] * 20
    assert spy_beta(flat, flat) is None
    fb = factor_book([1.0], ["X"], hist={"X": [0.01] * 5}, spy=[0.01] * 5)
    assert fb.spy_beta is None
    assert "spy_beta_assumed_1" not in fb.notes


def test_kills_daily_dd_stale_broker():
    halt, items = evaluate_kills(day_pnl_frac=-0.06, dd_frac=0.02, broker_connected=True)
    assert halt is True
    assert any(k.name == "daily_loss" and k.tripped for k in items)
    halt, items = evaluate_kills(dd_frac=0.12, broker_connected=True)
    assert any(k.name == "drawdown" and k.tripped for k in items)
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    halt, items = evaluate_kills(last_bar=old, broker_connected=True)
    assert any(k.name == "data_stale" and k.tripped for k in items)
    halt, items = evaluate_kills(broker_connected=False)
    assert any(k.name == "broker_disconnect" and k.tripped for k in items)
    halt, items = evaluate_kills(broker_connected=True, last_bar=datetime.now(timezone.utc))
    assert halt is False


def test_pretrade_cap_locate_pdt():
    env = pretrade_check(settings_cap=250, account_total=0, proposed_book_usd=300, notionals=[40], symbols=["AAA"])
    assert env.allow is False
    assert "exposure_cap" in env.reasons or "name_cap:AAA" in env.reasons
    assert env.deploy_cap == 250.0
    assert short_locate_proxy(side="long", notional_usd=1e6, adv_usd=1.0) is True
    assert short_locate_proxy(side="short", notional_usd=50_000, adv_usd=1_000_000) is False
    assert pdt_blocked(account_equity=10_000, day_trades_5d=3, is_us=True, would_day_trade=True) is True
    assert pdt_blocked(account_equity=30_000, day_trades_5d=3, is_us=True, would_day_trade=True) is False
    blocked = pretrade_check(
        settings_cap=250,
        account_total=10_000,
        proposed_book_usd=50,
        symbols=["AAA"],
        sides=["short"],
        notionals=[50],
        adv=[1_000_000],
        countries=["US"],
        day_trades_5d=3,
        would_day_trade=True,
    )
    assert blocked.pdt_blocked is True
    assert blocked.allow is False


def test_post_trade_is_and_audit_floor(tmp_path: Path):
    assert one_fill_is(100.0, 100.10, "buy") == pytest.approx(10.0)
    assert one_fill_is(100.0, 99.90, "sell") == pytest.approx(10.0)
    summary = summarize_symbol(
        "AAPL",
        [
            {"arrival_price": 100, "fill_price": 100.2, "side": "buy"},
            {"arrival_price": 100, "fill_price": 100.1, "side": "buy"},
        ],
    )
    assert summary.n == 2
    assert summary.mean_bps > 0
    from app.services.ops_desk.audit_size import record

    row = record(deploy_cap=250, weights={"AAA": 0.1}, veto=["pdt"], dest=tmp_path / "a.jsonl")
    assert row["deploy_cap"] == 250
    text = (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    assert "250" in text and "pdt" in text
    seal = seal_deploy_floor(250, 0, dest=tmp_path / "floor.json")
    assert seal["deploy_cap"] == 250.0
    assert read_floor(tmp_path / "floor.json") == 250.0


def test_backup_last_good(tmp_path: Path):
    src = tmp_path / "digest.json"
    src.write_text('{"ok": true}', encoding="utf-8")
    feat = tmp_path / "features"
    feat.mkdir()
    (feat / "A.json").write_text("{}", encoding="utf-8")
    dest = tmp_path / "lg"
    out = backup_last_good([src, feat, tmp_path / "missing"], dest_root=dest)
    assert "digest.json" in out["copied"]
    assert (dest / "digest.json").is_file()
    assert (dest / "features" / "A.json").is_file()
    assert any("missing" in s for s in out["skipped"])


def test_construct_kill_switch_flattens_new_risk():
    from app.services.construction.construct import construct_sleeve

    rows = [{"symbol": "AAA", "p_beat_21": 0.8, "vol": 0.2, "adv_usd": 1e7, "price": 10, "atr": 0.3}]
    book = construct_sleeve(rows, settings_cap=250, account_total=250, dd_frac=0.25)
    assert book["ops"] is not None
    assert book["ops"]["kills"]["halt"] is True
    assert book["holdings"] == []
    assert book["cash_usd"] == 250.0
    assert book["ops"]["dr_floor"] == 250.0


def test_desk_tca_and_stress_on_book(tmp_path: Path):
    from app.services.ops_desk.desk import evaluate_desk

    rng = np.random.default_rng(3)
    hist = {"AAA": rng.normal(0, 0.01, 50).tolist()}
    spy = rng.normal(0, 0.01, 50).tolist()
    desk = evaluate_desk(
        symbols=["AAA"],
        weights=[0.1],
        notionals=[25],
        settings_cap=250,
        account_total=250,
        hist=hist,
        spy=spy,
        betas=[1.0],
        fills_by_symbol={"AAA": [{"arrival_price": 10, "fill_price": 10.02, "side": "buy"}]},
        audit_path=tmp_path / "sz.jsonl",
        seal_path=tmp_path / "fl.json",
        broker_connected=True,
        last_bar=datetime.now(timezone.utc),
    )
    assert desk["pretrade"]["allow"] is True
    assert desk["deploy_cap"] == 250
    assert len(desk["stress"]) == 3
    assert desk["tca"][0]["n"] == 1
    assert desk["audit"]["deploy_cap"] == 250


def test_stale_without_bar_trips():
    halt, items = evaluate_kills(last_bar=None, broker_connected=True)
    assert halt is True
    assert any(k.name == "data_stale" and k.tripped for k in items)


def test_unknown_broker_trips():
    halt, items = evaluate_kills(last_bar=datetime.now(timezone.utc), broker_connected=None)
    assert halt is True
    assert any(k.name == "broker_disconnect" and k.tripped for k in items)


def test_live_sensors_empty_names_no_last_bar():
    from app.services.ops_desk.live_hooks import live_sensors

    sn = live_sensors([])
    assert sn["last_bar"] is None
    assert sn["broker_connected"] is not True


def test_allocate_does_not_kill_on_construction_sensors(monkeypatch):
    """Kill switch is enforced on the live order path, not by rewriting construction tickets."""
    from app.services.risk.maneuver_generator import ManeuverOutput
    from app.services.risk.portfolio_sizing import allocate_deploy_budget
    from app.services.ops_desk.live_hooks import reject_new_order

    m = ManeuverOutput(
        rank=1,
        ticker="AAA",
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
        position_size_usd=80.0,
        expected_return_low=3.0,
        expected_return_high=6.0,
        expected_pnl_low=12.0,
        expected_pnl_high=24.0,
        confidence=0.9,
        time_horizon="1–5 days",
        catalyst="test",
        rationale="test",
        execution_plan="Размер: $80.",
    )
    outs = allocate_deploy_budget([m], 250.0)
    assert float(outs[0].position_size_usd) > 0.0
    halt = reject_new_order(
        ticker="AAA",
        side="buy",
        qty=1,
        price=10,
        settings_cap=250,
        sensors={"day_pnl_frac": 0.0, "dd_frac": 0.25, "last_bar": None, "broker_connected": True},
    )
    assert halt and "kill_switch" in halt


def test_reject_new_order_kill_and_cap():
    from app.services.ops_desk.live_hooks import reject_new_order

    ok = reject_new_order(
        ticker="AAA",
        side="buy",
        qty=1,
        price=10,
        settings_cap=250,
        account_total=250,
        sensors={"day_pnl_frac": 0.0, "dd_frac": 0.0, "last_bar": datetime.now(timezone.utc), "broker_connected": True},
    )
    assert ok is None
    halt = reject_new_order(
        ticker="AAA",
        side="buy",
        qty=1,
        price=10,
        settings_cap=250,
        sensors={"day_pnl_frac": -0.08, "dd_frac": 0.0, "last_bar": None, "broker_connected": True},
    )
    assert halt and "kill_switch" in halt
    fat = reject_new_order(
        ticker="AAA",
        side="buy",
        qty=20,
        price=20,
        settings_cap=250,
        account_total=250,
        sensors={"day_pnl_frac": 0.0, "dd_frac": 0.0, "last_bar": datetime.now(timezone.utc), "broker_connected": True},
    )
    assert fat and "pretrade" in fat


def test_order_cap_zero_is_not_replaced_with_250(monkeypatch):
    from app.core.config import settings
    from app.services.ops_desk.live_hooks import order_capital_cap, reject_new_order

    monkeypatch.setattr(settings, "DEFAULT_PORTFOLIO_SIZE", 0.0)
    assert order_capital_cap(None) is None
    msg = reject_new_order(
        ticker="AAA",
        side="buy",
        qty=1,
        price=10,
        settings_cap=None,
        sensors={"day_pnl_frac": 0.0, "dd_frac": 0.0, "last_bar": None, "broker_connected": True},
    )
    assert msg == "нет данных"


def test_tca_from_own_tape(tmp_path, monkeypatch):
    from app.services.execution.fill_tape import append_fill, load_fills
    from app.services.ops_desk.live_hooks import fills_grouped
    from app.services.ops_desk.tca_post import book_tca

    dest = tmp_path / "fills.jsonl"
    monkeypatch.setattr("app.services.execution.fill_tape.tape_path", lambda: dest)
    append_fill({"symbol": "AAA", "arrival_price": 10, "fill_price": 10.02, "side": "buy"}, dest=dest)
    grouped = fills_grouped(load_fills(dest=dest))
    tca = book_tca(grouped)
    assert tca[0].n == 1
    assert tca[0].mean_bps > 0


def test_nightly_ops_dr_seals_250(tmp_path):
    from app.services.ops_desk.live_hooks import run_nightly_dr

    digest = tmp_path / "latest.json"
    digest.write_text('{"as_of": "2026-09-21"}', encoding="utf-8")
    feat = tmp_path / "features"
    feat.mkdir()
    (feat / "A.json").write_text("[]", encoding="utf-8")
    dest = tmp_path / "lg"
    seal = tmp_path / "floor.json"
    out = run_nightly_dr(
        settings_cap=250,
        account_total=0,
        dest_root=dest,
        seal_path=seal,
        sources=[digest, feat],
    )
    assert out["seal"]["deploy_cap"] == 250.0
    assert (dest / "latest.json").is_file()
    assert (dest / "features" / "A.json").is_file()


def test_ff_percent_scale_and_empty_mom():
    rng = np.random.default_rng(4)
    mkt = rng.normal(0.04, 1.0, 40)  # percent
    asset = 1.1 * (mkt / 100.0) + rng.normal(0, 0.001, 40)
    ff = [{"Mkt-RF": float(mkt[i]), "SMB": 0.1, "HML": -0.1} for i in range(40)]
    ld = ff_loadings(list(asset), ff)
    assert ld["mkt"] == pytest.approx(1.1, rel=0.35)
    # Mom column missing → OLS still returns mkt/smb/hml
    assert "mom" not in ld
    assert "smb" in ld
