"""Desk operators — Turtle vol, purged CV, LSM, gates, no-arb."""
from __future__ import annotations

from app.services.quant_desk.convex_alloc import inverse_vol_weights, project_capped_simplex
from app.services.quant_desk.cross_section import rank_01, zscore
from app.services.quant_desk.lsm_exercise import lsm_hold_or_close
from app.services.quant_desk.measure import one_step_binomial_no_arb, physical_factory_ok
from app.services.quant_desk.microstructure import book_gate, margin_buffer
from app.services.quant_desk.monte_carlo import antithetic_mean
from app.services.quant_desk.overlays import desk_overlay
from app.services.quant_desk.purged_cv import purged_walk_forward
from app.services.quant_desk.vol_target import turtle_unit_usd, vol_target_scale


def test_turtle_unit_scales_inverse_to_atr():
    cheap = turtle_unit_usd(equity_usd=100_000, price=100, atr=1)
    wild = turtle_unit_usd(equity_usd=100_000, price=100, atr=4)
    assert cheap > wild * 3.5
    assert vol_target_scale(current_usd=10_000, equity_usd=100_000, price=100, atr=2) >= 0.4


def test_purged_folds_do_not_overlap_embargo():
    folds = purged_walk_forward(200, n_splits=3, embargo=5, min_train=40)
    assert folds
    for train, test in folds:
        assert train
        assert test
        assert max(train) < min(test)


def test_lsm_prefers_continuation_when_paths_pay():
    dec = lsm_hold_or_close(
        mark_pnl=1.0,
        remaining_payoffs=[3.0, 4.0, 5.0, 6.0],
        state_features=[0.2, 0.4, 0.6, 0.8],
    )
    assert dec.hold is True


def test_simplex_respects_cap():
    w = project_capped_simplex([0.9, 0.05, 0.05], cap=0.4)
    assert abs(sum(w) - 1) < 1e-6
    assert max(w) <= 0.4 + 1e-9
    iv = inverse_vol_weights([0.1, 0.2, 0.4])
    assert iv[0] > iv[1] > iv[2]


def test_book_gate_blocks_wide_spread_and_thin_buffer():
    blocked = book_gate(bid=100, ask=101.0, direction="long", max_spread=0.004)
    assert blocked.allow is False
    ok = book_gate(bid=100, ask=100.05, bid_sz=10, ask_sz=10, direction="long")
    assert ok.allow is True
    no_book_wild = book_gate(direction="long", atr_pct=0.08)
    assert no_book_wild.allow is True
    assert no_book_wild.size_mult < 1.0
    assert margin_buffer(leverage=10, maintenance=0.5) < margin_buffer(leverage=2, maintenance=0.25)


def test_binomial_no_arb_and_physical_factory():
    assert one_step_binomial_no_arb(spot=100, up=1.1, down=0.9, rate=0.01) is True
    assert one_step_binomial_no_arb(spot=100, up=1.01, down=1.05, rate=0.0) is False
    assert physical_factory_ok(uses_risk_neutral_drift=True) is False
    assert physical_factory_ok(uses_risk_neutral_drift=False) is True


def test_cross_section_and_antithetic():
    z = zscore([1.0, 2.0, 3.0])
    assert abs(sum(z)) < 1e-9
    r = rank_01([3, 1, 2])
    assert r[1] == 0.0 and r[0] == 1.0
    m = antithetic_mean(200, mu=0.0, sigma=1.0)
    assert abs(m) < 0.2


def test_fred_tilt_is_risk_off_when_vix_and_hy_spike():
    from app.services.quant_desk.alt_macro import blend_macro, esi_tilt, fama_french_tilt, fred_tilt

    tilt, parts = fred_tilt({"VIXCLS": 35.0, "BAMLH0A0HYM2": 8.0, "UNRATE": 8.0})
    calm, _ = fred_tilt({"VIXCLS": 12.0, "BAMLH0A0HYM2": 3.0, "UNRATE": 4.0})
    assert tilt < calm
    assert "VIXCLS" in parts
    ff, _ = fama_french_tilt({"Mkt-RF": 1.2, "Mom": 0.8, "HML": 0.1})
    assert ff > 0
    assert esi_tilt(10.0, 10.0, 10.0) > 0
    assert abs(blend_macro(0.5, -0.5, weights=[1, 1])) < 1e-9
    ov = desk_overlay(
        equity_usd=100_000,
        price=50,
        atr=1.0,
        current_usd=8_000,
        direction="long",
        realized_ann_vol=0.2,
        atr_pct=0.02,
    )
    assert ov.allow is True
    assert 0.4 <= ov.size_mult <= 1.2


def test_public_alt_parsers_and_source_map():
    from app.services.quant_desk.public_alt import cftc_lev_money_net_share, latest_jsonstat_value
    from app.services.quant_desk.source_map import QC_TO_OURS, practical_status

    payload = {
        "value": {"0": 1.0, "1": 12.5},
        "dimension": {"time": {"category": {"index": {"2024-01": 0, "2024-02": 1}}}},
    }
    assert latest_jsonstat_value(payload) == 12.5
    share = cftc_lev_money_net_share(
        [
            {
                "lev_money_positions_long_all": 120,
                "lev_money_positions_short_all": 80,
                "open_interest_all": 400,
            }
        ]
    )
    assert share == 0.1
    st = practical_status()
    assert "wired" in st and "licensed_key" in st
    assert any(row["qc"].startswith("Eurostat") for row in QC_TO_OURS)


def test_licensed_alt_parsers():
    from app.services.quant_desk.licensed_alt import (
        benzinga_headline_tilt,
        brain_row_sentiment,
        congress_net_tilt,
        pe_to_growth_tilt,
        spectral_ofi_tilt,
    )

    assert brain_row_sentiment({"sentiment_7d": 0.4}) == 0.4
    assert congress_net_tilt(
        [{"Transaction": "Purchase"}, {"Transaction": "Sale"}, {"Transaction": "Purchase"}]
    ) == (1 / 3)
    tilt = benzinga_headline_tilt(
        [{"title": "Futures surge after upgrade"}, {"title": "Bankruptcy plunge"}]
    )
    assert tilt is not None
    assert pe_to_growth_tilt(30.0) > 0
    assert spectral_ofi_tilt({"ofi": 0.25}) == 0.25


def test_fundamental_fa_cache_roundtrip(tmp_path, monkeypatch):
    from app.services.quant_desk import fundamental_fa as fa_mod

    monkeypatch.setattr(fa_mod, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(fa_mod, "_api_key", lambda: "")
    assert fa_mod.fetch_fundamentals("SPY") == {}
    row = {"symbol": "SPY", "pe": 22.0, "source": "test"}
    fa_mod._save_cache("SPY", row)
    got = fa_mod._load_cache("SPY")
    assert got is not None and got["pe"] == 22.0
    monkeypatch.setattr(fa_mod, "fetch_fundamentals", lambda *_a, **_k: {"pe": 30.0})
    from app.services.quant_desk.licensed_alt import pe_to_growth_tilt

    assert pe_to_growth_tilt(30.0) > 0



def test_qc_lean_ingest_reads_brain_and_congress(tmp_path, monkeypatch):
    from app.services.quant_desk import qc_lean_ingest as ingest

    brain = tmp_path / "alternative" / "brain" / "sentiment_usa"
    brain.mkdir(parents=True)
    (brain / "spy.csv").write_text("# comment\n20240102 00:00,0.42,-0.1\n", encoding="utf-8")
    quiver = tmp_path / "alternative" / "quiver" / "congresstrading"
    quiver.mkdir(parents=True)
    (quiver / "aapl.csv").write_text(
        "date,transaction\n20240102,Purchase\n20240103,Sale\n20240104,Purchase\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ingest.settings, "QUANTCONNECT_DATA_DIR", str(tmp_path))
    snap = ingest.ingest_qc_lean_snapshot()
    assert snap["brain_tilt"] == 0.42
    assert abs(float(snap["quiver_tilt"]) - (1 / 3)) < 1e-9
