from __future__ import annotations

from app.services.forecast.bar_quality import last_bar_sane
from app.services.forecast.daily_book import build_daily_book, realize_book
from app.services.forecast.meta_label import meta_label_take
from app.services.forecast.last_good import should_replace_artifact, write_cv_sidecar
from app.services.portfolio.capital_overlap import grid_occupied_tickers


def test_daily_book_empty_below_score_six():
    book = build_daily_book([{"symbol": "AAPL", "score_20": 5, "p_beat_20": 0.55}])
    assert book["count"] == 0
    assert book["holdings"] == []


def test_daily_book_conviction_weights_and_excess():
    book = build_daily_book(
        [
            {"symbol": "AAPL", "score_20": 8, "p_beat_20": 0.7},
            {"symbol": "MSFT", "score_20": 7, "p_beat_20": 0.65},
        ]
    )
    assert book["count"] == 2
    weights = [h["weight"] for h in book["holdings"]]
    assert abs(sum(weights) - 1.0) < 1e-6
    assert book["holdings"][0]["weight"] > book["holdings"][1]["weight"]
    assert book["scheme"].startswith("conviction_p_beat")
    realized = realize_book(book, {"AAPL": 0.02, "MSFT": 0.00}, 0.01)
    assert realized["realized"] is True
    assert realized["excess"] is not None


def test_meta_label_does_not_veto_without_p():
    assert meta_label_take(direction="long", p_calibrated=None, mesh_confidence=0.3) is True
    assert meta_label_take(direction="long", p_calibrated=0.4, mesh_confidence=0.4) is False
    assert meta_label_take(direction="long", p_calibrated=0.4, mesh_confidence=0.8) is True


def test_bar_quality_rejects_print_spike():
    assert last_bar_sane([100.0, 100.5]) is True
    assert last_bar_sane([100.0, 160.0]) is False


def test_grid_occupied_tickers_only_open_notional():
    bots = {
        "a": {
            "config": {"ticker": "NVDA"},
            "levels": [
                {"status": "filled", "side": "buy", "quantity": 1, "fill_price": 100},
            ],
            "summary": {"last_price": 110},
        },
        "b": {
            "config": {"ticker": "AAPL"},
            "levels": [],
        },
    }
    assert grid_occupied_tickers(bots) == {"NVDA"}


def test_cpcv_and_deflated_sharpe():
    from app.services.forecast.purged_cv import (
        combinatorial_purged_splits,
        deflated_sharpe_ratio,
        evaluate_cpcv_accuracy,
    )

    folds = combinatorial_purged_splits(120, n_groups=6, n_test_groups=2, label_horizon=5)
    assert len(folds) >= 10
    labels = [1 if i % 3 else -1 for i in range(80)]
    preds = list(labels)
    cpcv = evaluate_cpcv_accuracy(labels, preds, label_horizon=5)
    assert cpcv.accuracy >= 0.99
    dsr = deflated_sharpe_ratio([0.001] * 30, n_trials=4)
    assert dsr["n"] == 30
    assert 0.0 <= dsr["dsr"] <= 1.0


def test_paper_tca_buy_worse_than_mid():
    from app.services.execution.tca import apply_half_spread

    fill, meta = apply_half_spread(100.0, "buy", symbol="AAPL")
    assert fill > 100.0
    assert meta["model"] == "half_spread_paper"
    sell, _ = apply_half_spread(100.0, "sell", symbol="AAPL")
    assert sell < 100.0


def test_asof_join_uses_only_that_day(tmp_path, monkeypatch):
    from app.services.forecast import asof_store, pit_snapshots
    from app.services.forecast.forecast_features import build_feature_matrix

    monkeypatch.setattr(asof_store.settings, "PIT_STORE_DIR", str(tmp_path))
    monkeypatch.setattr(pit_snapshots.settings, "PIT_STORE_DIR", str(tmp_path))
    asof_store.persist_asof("AAA", {"fmp_roe": 0.22, "fund_present": 1.0}, as_of="2024-06-10")
    prices = [100.0 + i * 0.1 for i in range(40)]
    dates = ["2024-06-01"] * 39 + ["2024-06-10"]
    df = build_feature_matrix(prices, min_history=30, symbol="AAA", dates=dates)
    assert df.iloc[-1]["fmp_roe"] == 0.22
    assert df.iloc[-1]["fund_present"] == 1.0
    assert df.iloc[0]["fmp_roe"] == 0.0
    assert asof_store.extras_as_of("AAA", None) == {}


def test_asof_store_roundtrip(tmp_path, monkeypatch):
    from app.services.forecast import asof_store

    monkeypatch.setattr(asof_store.settings, "PIT_STORE_DIR", str(tmp_path))
    asof_store.persist_asof("aapl", {"ret_5": 0.01, "junk": "x"}, as_of="2026-01-02")
    loaded = asof_store.load_asof("AAPL", "2026-01-02")
    assert loaded["ret_5"] == 0.01
    assert asof_store.load_asof("AAPL", "1999-01-01") == {}


def test_registry_canary_off_by_default(tmp_path, monkeypatch):
    import app.services.forecast.model_registry as reg
    import app.services.ml.model as model_mod

    monkeypatch.setattr(model_mod, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(reg, "MODEL_DIR", tmp_path)
    assert reg.is_canary_symbol("AAPL") is False
    reg.set_alias("live", "m1", ece=0.05, cv=0.6)
    assert reg.get_alias("live") == "m1"
    assert reg.maybe_promote_shadow(new_ece=0.2, old_ece=0.05, new_cv=0.55, model_name="m2") is False
    assert reg.get_alias("live") == "m1"


def test_quote_tca_uses_ask_for_buy():
    from app.services.execution.tca import apply_quote_or_spread

    fill, meta = apply_quote_or_spread(100.0, "buy", bid=99.5, ask=100.5)
    assert fill == 100.5
    assert meta["model"] == "quote_bid_ask_paper"


def test_book_turnover_half_l1():
    from app.services.forecast.tear_sheet import book_turnover

    a = {"holdings": [{"symbol": "AAPL", "weight": 1.0}]}
    b = {"holdings": [{"symbol": "MSFT", "weight": 1.0}]}
    assert book_turnover(a, b) == 1.0
    assert book_turnover(a, a) == 0.0


def test_ece_and_kelly_and_dq():
    from app.services.forecast.bar_quality import bars_dq
    from app.services.forecast.calibration import (
        expected_calibration_error,
        kelly_mult,
        score_1_10,
    )
    from app.services.forecast.drift import population_stability_index

    report = expected_calibration_error([0.9] * 25 + [0.1] * 25, [1] * 25 + [0] * 25)
    assert report["n"] == 50
    assert report["reliable"] is True
    bad = expected_calibration_error([0.9] * 50, [0] * 50)
    assert bad["reliable"] is False
    score, trusted = score_1_10(0.9, ece_report=bad)
    assert score == 5 and trusted is False
    assert kelly_mult(0.5) == 0.0
    assert kelly_mult(0.9) == 1.0
    assert bars_dq([100, 100.1, 100.2, 100.3, 100.4])["ok"] is True
    assert bars_dq([100, 100, 100, 100, 180])["ok"] is False
    psi = population_stability_index([0.01] * 30, [0.01] * 30)
    assert psi < 0.05


def test_capital_slots_do_not_borrow():
    from app.services.portfolio.capital_slots import grid_capital_used, slot_room_usd

    assert slot_room_usd(100_000, "grid", 10_000) == 25_000
    assert slot_room_usd(100_000, "cash", 0) == 20_000
    bots = {
        "a": {"created_by": "u@x", "is_active": True, "config": {"total_capital": 3000}},
        "b": {"created_by": "other", "is_active": True, "config": {"total_capital": 9000}},
    }
    assert grid_capital_used(bots, owner_email="u@x") == 3000.0


def test_maneuver_occupied_tickers():
    from types import SimpleNamespace

    from app.services.portfolio.capital_overlap import maneuver_occupied_tickers

    assert maneuver_occupied_tickers([SimpleNamespace(ticker="aapl")]) == {"AAPL"}


def test_last_good_keeps_better_sidecar(tmp_path):
    side = tmp_path / "m.cv.json"
    write_cv_sidecar(side, cv=0.62, n=40)
    assert should_replace_artifact(side, new_cv=0.50, new_n=40) is False
    assert should_replace_artifact(side, new_cv=0.64, new_n=40) is True
