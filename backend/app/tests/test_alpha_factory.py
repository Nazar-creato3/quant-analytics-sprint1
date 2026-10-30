"""Alpha factory: every research/B bullet has an executable operator + test."""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.services.alpha.books import cross_sectional_ls, dual_books, retail_long_only
from app.services.alpha.feature_lineage import resolve_store_dir
from app.services.alpha.horizons import ALPHA_HORIZONS, excess_stack, latest_excess_map
from app.services.alpha.labels import primary_labels
from app.services.alpha.model_card import build_card, human_promote, promote_to_prod
from app.services.alpha.nested_cpcv import Candidate, nested_cpcv_select
from app.services.alpha.neutralization import neutralize_cs
from app.services.alpha.regime_gate import detect_regime, gaussian_hmm, two_state_hmm
from app.services.alpha.rules import donchian_breakout, primary_side, simulate_turtle, turtle_breakout
from app.services.alpha.veto import GateInputs, VETO_HIERARCHY, combine
from app.services.forecast.feature_store import ForecastFeatureStore
from app.services.forecast.purged_cv import combinatorial_purged_splits
from app.services.quant_desk.cross_section import neutralize


def _trend(n: int = 80, step: float = 0.4) -> list[float]:
    return [100.0 + step * i for i in range(n)]


def test_excess_stack_is_1_5_21_not_single_lgbm():
    assert ALPHA_HORIZONS == (1, 5, 21)
    closes = _trend(60)
    bench = _trend(60, 0.1)
    stack = excess_stack(closes, bench)
    assert set(stack) == {1, 5, 21}
    for h, labels in stack.items():
        assert len(labels) == len(closes)
        assert any(x != 0 for x in labels[: len(closes) - h])
        assert labels[-1] == 0  # last bar has no completed forward window
    latest = latest_excess_map(closes, bench)
    assert latest["excess_1d"] is not None
    assert latest["excess_5d"] is not None
    assert latest["excess_21d"] is not None


def test_cs_neutralization_kills_sector_and_size():
    # y is exactly sector dummy + log-size + beta — residual must vanish.
    sectors = ["tech", "tech", "tech", "staples", "staples", "staples"]
    size = [1e9, 2e9, 3e9, 1e9, 2e9, 3e9]
    beta = [0.8, 1.0, 1.2, 0.8, 1.0, 1.2]
    values = []
    for i, (sec, sz, b) in enumerate(zip(sectors, size, beta)):
        values.append((10.0 if sec == "tech" else 0.0) + 2.0 * np.log(sz) + 0.5 * b)
    neu = neutralize_cs(values, sectors=sectors, size=size, beta=beta)
    assert max(abs(r) for r in neu.residual) < 1e-8
    wrapped = neutralize(values, sectors=sectors, size=size, beta=beta)
    assert wrapped == list(neu.z)


def test_nested_cpcv_does_not_select_on_outer_test():
    rng = np.random.default_rng(0)
    n = 96
    X = rng.normal(size=(n, 3))
    y = np.where(X[:, 0] > 0, 1, -1)

    def fit_predict(Xtr, ytr, Xte, params):
        # "good" uses feature 0; "leak" memorizes a constant that only fits train if params say so.
        if params["kind"] == "good":
            return np.where(Xte[:, 0] > 0, 1, -1)
        fill = int(np.sign(np.mean(ytr))) or 1
        return np.full(len(Xte), fill)

    sel = nested_cpcv_select(
        X,
        y,
        (Candidate("good", {"kind": "good"}), Candidate("constant", {"kind": "const"})),
        fit_predict,
        label_horizon=5,
        n_groups=6,
        n_test_groups=2,
    )
    assert sel.method == "nested_combinatorial_purged_cv"
    assert sel.winner.name == "good"
    assert sel.outer_n > 0
    folds = combinatorial_purged_splits(n, n_groups=6, n_test_groups=2, label_horizon=5)
    assert folds
    for f in folds:
        assert not (set(f.train_indices) & set(f.test_indices))


def test_feature_store_freeze_equals_live_replay(tmp_path):
    live = tmp_path / "store"
    store = ForecastFeatureStore(store_dir=live)
    n = store.materialize_from_prices("AAPL", _trend(40))
    assert n > 0
    lin = store.lineage()
    assert lin is not None
    assert lin.columns
    dest = store.freeze("bt_2020")
    assert dest.is_dir()
    assert (dest / "FROZEN").is_file()
    assert (dest / "registry.json").is_file()
    reg = json.loads((dest / "registry.json").read_text(encoding="utf-8"))
    assert reg["feature_views"][0]["name"] == "forecast_tech"
    assert (live / "registry.json").is_file() or (live / "materializations.jsonl").is_file()
    frozen = ForecastFeatureStore(store_dir=live, freeze_id="bt_2020")
    live_row = store.latest_features("AAPL")
    froze_row = frozen.latest_features("AAPL")
    assert live_row is not None and froze_row is not None
    assert live_row.features == froze_row.features
    with pytest.raises(RuntimeError):
        frozen.materialize_from_prices("AAPL", _trend(45))
    assert resolve_store_dir(live, "bt_2020") == dest
    # Live materialize after freeze must not mutate the frozen snapshot.
    store.materialize_from_prices("MSFT", _trend(40, -0.2))
    still = ForecastFeatureStore(store_dir=live, freeze_id="bt_2020")
    assert still.latest_features("MSFT") is None
    assert still.latest_features("AAPL") is not None


def test_primary_labels_are_tb_plus_meta():
    # Jump large enough to hit the upper ATR barrier.
    prices = [100.0] * 40 + [100.0 + 8.0 * (i + 1) for i in range(40)]
    lab = primary_labels(prices, horizon=5)
    assert lab.recipe == "triple_barrier+meta_label"
    assert lab.n_side > 0
    assert len(lab.side) == len(prices)
    assert all(m in (0, 1) for m in lab.meta_take)
    # Meta take only where both rule and barrier fired.
    rule = primary_side(prices)
    for s, r, m in zip(lab.side, rule, lab.meta_take):
        if m == 1:
            assert s != 0 and r != 0 and s == r


def test_veto_hierarchy_regime_beats_rules_beats_ml():
    assert VETO_HIERARCHY[0] == "regime"
    assert VETO_HIERARCHY[-1] == "ml"
    flat = combine(
        GateInputs(regime_alpha_on=False, donchian_dir=1, turtle_dir=1, ml_dir=1)
    )
    assert flat.direction == 0 and flat.vetoed_by == "regime"
    macro = combine(
        GateInputs(macro_veto=True, donchian_dir=1, turtle_dir=1, ml_dir=-1)
    )
    assert macro.vetoed_by == "macro"
    conflict = combine(GateInputs(donchian_dir=1, turtle_dir=-1, ml_dir=1))
    assert conflict.vetoed_by == "rules_conflict"
    skip = combine(GateInputs(donchian_dir=1, meta_take=False, ml_dir=1))
    assert skip.vetoed_by == "meta_skip"
    rules = combine(GateInputs(donchian_dir=1, turtle_dir=0, ml_dir=-1))
    assert rules.source == "rules" and rules.direction == 1
    ml = combine(GateInputs(ml_dir=-1))
    assert ml.source == "ml" and ml.direction == -1


def test_turtle_and_donchian_fire_on_breakout():
    # Long base so S1/S2 can arm, then a clean 20d breakout with room to pyramid.
    base = [100.0] * 70 + [100.0 + i * 2.0 for i in range(16)]
    don = donchian_breakout(base, lookback=20)
    assert don.direction == 1
    pos = simulate_turtle(base)
    assert pos.direction == 1
    assert pos.units >= 1
    assert pos.system in {"s1", "s2"}
    assert pos.unit_usd > 0
    assert pos.stop < base[-1]
    tur = turtle_breakout(base, lookback=55)
    assert tur.family == "turtle"
    assert tur.direction == 1


def test_regime_gate_vix_curve_credit_and_hmm():
    on = detect_regime(breadth=0.4, vix=14.0, curve=0.8, credit=0.4)
    assert on.alpha_on is True and on.size_mult == 1.0
    off = detect_regime(breadth=-0.5, vix=18.0, curve=-0.2, credit=2.0)
    assert off.alpha_on is False
    shock = detect_regime(
        breadth=-0.1,
        vix=40.0,
        curve=-0.3,
        credit=2.5,
        vix_history=[12.0] * 20 + [40.0],
    )
    assert shock.macro_veto is True
    assert shock.alpha_on is False
    state = two_state_hmm([0.0] * 20 + [5.0] * 20)
    assert state in (0, 1)
    fit = gaussian_hmm([0.0] * 30 + [4.0] * 30)
    assert fit.last_state in (0, 1, 2)
    assert len(fit.posterior) == 3
    assert abs(sum(fit.posterior) - 1.0) < 1e-6
    assert on.method == "threshold+hmm3_baumwelch"


def test_dual_books_cs_ls_and_retail_long_only():
    rows = [
        {"symbol": f"N{i}", "score_20": 9 - i, "p_beat_20": 0.7 - i * 0.02, "cs_score": 3 - i}
        for i in range(8)
    ]
    dual = dual_books(rows, as_of="2026-09-21", cap_usd=250.0, min_score=6)
    cs = dual.cross_sectional
    assert cs.holdings
    longs = [h for h in cs.holdings if h["side"] == "long"]
    shorts = [h for h in cs.holdings if h["side"] == "short"]
    assert longs and shorts
    assert abs(cs.net) < 1e-6
    assert abs(cs.gross - 1.0) < 1e-6
    retail = dual.retail_long_only
    assert retail.holdings
    assert all(h["side"] == "long" for h in retail.holdings)
    notionals = [float(h["notional_usd"]) for h in retail.holdings]
    assert sum(notionals) <= 250.0 + 1e-6
    empty = retail_long_only(rows, cap_usd=0)
    assert empty.holdings == ()
    tiny = cross_sectional_ls(rows[:2])
    assert tiny.note == "universe_too_small"


def test_model_card_promote_requires_freeze():
    card = build_card(
        name="alpha_demo",
        metrics={"accuracy": 0.55, "outer_accuracy": 0.55, "outer_n": 40},
        n_train=40,
        feature_lineage="abc",
        feature_freeze_id=None,
        promoted=True,
    )
    with pytest.raises(ValueError):
        promote_to_prod(card)
    ok = build_card(
        name="alpha_demo",
        metrics={"accuracy": 0.55, "outer_n": 40},
        n_train=40,
        feature_lineage="abc",
        feature_freeze_id="bt_2020",
        promoted=False,
        horizons=ALPHA_HORIZONS,
    )
    result = promote_to_prod(ok)
    assert result["model_card"]["cv_method"] == "nested_combinatorial_purged_cv"
    assert result["model_card"]["label_recipe"] == "triple_barrier+meta_label"
    assert result["model_card"]["horizons"] == [1, 5, 21]
    assert result["model_card"]["veto_hierarchy"] == list(VETO_HIERARCHY)


def test_daily_book_exposes_sleeves():
    from app.services.forecast.daily_book import build_daily_book

    rows = [
        {"symbol": f"N{i}", "score_20": 8, "p_beat_20": 0.66}
        for i in range(6)
    ]
    book = build_daily_book(rows, retail_cap_usd=250)
    assert book["count"] == 6
    assert "cross_sectional" in book["sleeves"]
    assert "retail_long_only" in book["sleeves"]


def test_pipeline_regime_includes_alpha_gate():
    import pandas as pd

    from app.services.pipeline.market_regime import compute_market_regime

    idx = pd.date_range("2026-01-01", periods=60, freq="D")
    spy = pd.DataFrame(
        {
            "open": np.linspace(100, 120, 60),
            "high": np.linspace(101, 122, 60),
            "low": np.linspace(99, 118, 60),
            "close": np.linspace(100, 120, 60),
            "volume": np.full(60, 1e6),
        },
        index=idx,
    )
    payload = compute_market_regime({"SPY": spy})
    assert "alpha_on" in payload
    assert "size_mult" in payload
    assert "regime_gate" in payload


def test_human_promote_requires_confirm_and_reviewer():
    card = build_card(
        name="alpha_demo",
        metrics={"accuracy": 0.56, "outer_accuracy": 0.56, "outer_n": 40},
        n_train=40,
        feature_lineage="abc",
        feature_freeze_id="bt_2020",
        promoted=False,
    )
    with pytest.raises(ValueError, match="confirm"):
        human_promote(card, confirm=False, reviewer="desk")
    with pytest.raises(ValueError, match="reviewer"):
        human_promote(card, confirm=True, reviewer="")
    out = human_promote(card, confirm=True, reviewer="desk")
    assert out["model_card"]["promoted"] is True
    assert "desk" in out["model_card"]["note"]


def test_market_beat_primary_is_1_5_21():
    from app.services.forecast.forecast_features import build_forecast_feature_row
    from app.services.forecast.market_beat import build_market_beat

    prices = list(np.linspace(100, 110, 40))
    payload = build_market_beat(
        symbol="AAPL",
        p_beat_1=0.61,
        p_beat_5=0.72,
        p_beat_21=0.68,
        features=build_forecast_feature_row(prices),
        prices=prices,
    )
    assert payload["primary_horizons"] == [1, 5, 21]
    assert payload["score_5"] == 7
    assert payload["score_21"] == payload["score_20"]
    assert payload["p_beat_20"] == payload["p_beat_21"]
