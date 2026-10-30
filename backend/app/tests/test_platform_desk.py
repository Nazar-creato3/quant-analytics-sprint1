"""F. Platform product — report, IPS, promotion, monitor, nightly."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.services.platform_desk.mandate import IPS, apply_mandate, esg_hits, save_ips, ticker_blocked
from app.services.platform_desk.monitor import calibration_vs_hit
from app.services.platform_desk.reporting import brinson_lite, build_client_pack, persist_client_pack, risk_contributions, tear_metrics
from app.services.platform_desk.runbook import desks


def test_tear_and_quantstats_optional():
    rng = np.random.default_rng(1)
    r = rng.normal(0.0004, 0.01, 60).tolist()
    t = tear_metrics(r)
    assert t["n"] == 60
    assert t["sharpe"] is not None
    assert t["max_dd"] < 0 or t["max_dd"] == 0
    thin = tear_metrics([0.01])
    assert thin["n"] == 1
    assert thin.get("note") == "thin_sample"


def test_brinson_identity_and_rc():
    out = brinson_lite(
        {"tech": 0.6, "health": 0.4},
        {"tech": 0.5, "health": 0.5},
        {"tech": 0.02, "health": 0.00},
        {"tech": 0.01, "health": 0.01},
    )
    assert out["active"] == pytest.approx(out["allocation"] + out["selection"] + out["interaction"])
    assert out["active"] != 0
    rng = np.random.default_rng(2)
    hist = {"AAA": rng.normal(0, 0.01, 40).tolist(), "BBB": rng.normal(0, 0.01, 40).tolist()}
    rc = risk_contributions([0.4, 0.4], ["AAA", "BBB"], hist=hist)
    assert len(rc) == 2
    assert sum(x["rc_pct"] for x in rc) == pytest.approx(1.0, abs=0.02)


def test_ips_ban_esg_and_allocate(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.platform_desk.mandate._root", lambda: tmp_path)
    ips = save_ips(
        IPS(
            user_id="u1",
            deploy_cap=250,
            max_risk_pct=2.0,
            banned_tickers=("TOX",),
            esg_keywords=("coal",),
            max_name_frac=0.1,
            updated_at="",
        )
    )
    assert ticker_blocked("TOX", ips) == "ips_banned:TOX"
    assert ticker_blocked("AAA", ips, headlines="coal mine expansion") == "ips_esg:coal"
    assert ticker_blocked("AAA", ips, headlines="software update") is None
    assert esg_hits("coal fire", ["coal"]) == ["coal"]

    banned = SimpleNamespace(
        ticker="TOX",
        is_no_trade=False,
        strategy_type="momentum",
        risk_percent=2.0,
        position_size_usd=25.0,
        catalyst="ok",
        rationale="ok",
        note="",
    )
    apply_mandate([banned], user_id="u1", deploy_cap=250)
    assert banned.is_no_trade is True


def test_ips_cannot_raise_operator_cap(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.platform_desk.mandate._root", lambda: tmp_path)
    save_ips(
        IPS(
            user_id="paper",
            deploy_cap=10_000,
            max_risk_pct=2.0,
            banned_tickers=(),
            esg_keywords=(),
            max_name_frac=0.1,
            updated_at="",
        )
    )
    from app.services.risk.maneuver_generator import ManeuverOutput
    from app.services.risk.portfolio_sizing import allocate_deploy_budget

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
    allocate_deploy_budget([m], 250.0, user_id="paper")
    assert float(m.position_size_usd) <= 250.0
    assert float(m.position_size_usd) < 100.0


def test_construct_respects_banned_ips(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.platform_desk.mandate._root", lambda: tmp_path)
    save_ips(
        IPS(
            user_id="paper",
            deploy_cap=250,
            max_risk_pct=2.0,
            banned_tickers=("BBB",),
            esg_keywords=(),
            max_name_frac=0.1,
            updated_at="",
        )
    )
    from app.services.construction.construct import construct_sleeve

    book = construct_sleeve(
        [
            {"symbol": "AAA", "p_beat_21": 0.8, "vol": 0.2, "adv_usd": 1e7, "price": 10, "atr": 0.3},
            {"symbol": "BBB", "p_beat_21": 0.9, "vol": 0.2, "adv_usd": 1e7, "price": 10, "atr": 0.3},
        ],
        settings_cap=250,
        account_total=250,
        user_id="paper",
    )
    names = {h["symbol"] for h in book["holdings"]}
    assert "BBB" not in names


def test_client_pack_persist_and_nightly(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.services.platform_desk.reporting._book_dir", lambda: tmp_path)
    monkeypatch.setattr("app.services.forecast.daily_book._book_dir", lambda: tmp_path)
    monkeypatch.setattr("app.services.platform_desk.monitor._dir", lambda: tmp_path)
    book = {
        "as_of": "2026-09-21",
        "holdings": [
            {"symbol": "AAA", "weight": 0.1, "sector": "tech", "p_beat_21": 0.7},
        ],
    }
    pack = build_client_pack(
        book=book,
        realized={**book, "excess": 0.01},
        excess_hist=[0.002, -0.001, 0.003],
        asset_returns={"AAA": 0.01},
        bench_sector_w={"tech": 1.0},
        bench_sector_ret={"tech": 0.0},
    )
    assert pack["tear"]["n"] >= 3
    assert pack["brinson"]["sectors"]
    path = persist_client_pack(pack, user_id="paper")
    assert path is not None
    assert (tmp_path / "clients" / "paper" / "latest.client.json").is_file()

    monkeypatch.setattr("app.services.forecast.daily_book.load_book", lambda: book)
    monkeypatch.setattr("app.services.forecast.daily_book.excess_history", lambda: [0.002])
    from app.services.platform_desk.nightly import run_nightly_platform

    out = run_nightly_platform(book=book, realized={**book, "excess": 0.01}, asset_returns={"AAA": 0.01})
    assert out["report"]["holdings_n"] == 1
    assert "freshness" in out["monitor"]


def test_calibration_needs_20_and_ece():
    thin = calibration_vs_hit([0.6] * 10, [True] * 10)
    assert thin["ece"] is None
    conf = [0.2] * 10 + [0.8] * 10
    hits = [False] * 8 + [True] * 2 + [True] * 8 + [False] * 2
    cal = calibration_vs_hit(conf, hits)
    assert cal["n"] == 20
    assert cal["ece"] is not None
    assert cal["ece"] >= 0


def test_promote_mfa_refuses(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.platform_desk.promotion._log_path", lambda: tmp_path / "s.jsonl")
    from app.services.alpha.model_card import build_card
    from app.services.platform_desk.promotion import promote_with_signoff

    card = build_card(
        name="x",
        metrics={"outer_accuracy": 0.55, "outer_n": 40},
        n_train=40,
        feature_lineage="pit",
        feature_freeze_id="fz1",
    )
    with pytest.raises(ValueError, match="MFA"):
        promote_with_signoff(card, confirm=True, reviewer="cio", totp_ok=False)

    monkeypatch.setattr(
        "app.services.platform_desk.promotion.human_promote",
        lambda c, confirm, reviewer: {"ok": True, "name": c.name},
    )
    out = promote_with_signoff(card, confirm=True, reviewer="cio", totp_ok=None)
    assert out["ok"] is True
    text = (tmp_path / "s.jsonl").read_text(encoding="utf-8")
    assert "cio" in text


def test_runbook_has_all_desks():
    ids = {d["id"] for d in desks()}
    assert ids == {"cio", "pm", "risk", "exec", "research", "ops", "client"}


def test_reject_order_mandate(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.platform_desk.mandate._root", lambda: tmp_path)
    save_ips(
        IPS(
            user_id="paper",
            deploy_cap=250,
            max_risk_pct=2.0,
            banned_tickers=("EVIL",),
            esg_keywords=(),
            max_name_frac=0.1,
            updated_at="",
        )
    )
    from app.services.ops_desk.live_hooks import reject_new_order

    msg = reject_new_order(
        ticker="EVIL",
        side="buy",
        qty=1,
        price=10,
        settings_cap=250,
        sensors={"day_pnl_frac": 0.0, "dd_frac": 0.0, "last_bar": datetime.now(timezone.utc), "broker_connected": True},
        user_id="paper",
    )
    assert msg and "mandate" in msg
