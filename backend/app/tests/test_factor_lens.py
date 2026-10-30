"""Prompt 65: orthogonal lens, Euler shares, ENB, API."""
from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.services.factor_lens.decompose import factor_variance_shares
from app.services.factor_lens.enb import diversification_ratio, enb_min_torsion, enb_pca
from app.services.factor_lens.ingest import rebuild_from_fixture
from app.services.factor_lens.names import FACTOR_ORDER
from app.services.factor_lens.orthogonalize import pairwise_abs_corr, sequential_orthogonalize
from app.services.factor_lens.store import reset as reset_factors
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.risk_engine.series import put_series, reset as reset_series
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_factor_lens", True)
    get_book().reset()
    reset_series()
    reset_factors()


def teardown_function() -> None:
    get_book().reset()
    reset_series()
    reset_factors()
    reset_for_tests()
    clear_session_user()


def test_skfolio_pinned() -> None:
    from app.services.factor_lens.moments import SKFOLIO_VERSION

    assert SKFOLIO_VERSION == "0.6.0"


def test_enb_one_name_is_one() -> None:
    assert abs(enb_pca([1.0], [[0.04]]) - 1.0) < 1e-9
    assert abs(enb_min_torsion([1.0], [[0.04]]) - 1.0) < 1e-6


def test_enb_n_independent_equal() -> None:
    n = 4
    cov = np.eye(n) * 0.04
    w = [1 / n] * n
    assert abs(enb_pca(w, cov) - n) < 0.1
    assert abs(enb_min_torsion(w, cov) - n) < 0.1


def test_diversification_ratio_hand() -> None:
    cov = [[0.04, 0.0], [0.0, 0.04]]
    dr = diversification_ratio([0.5, 0.5], cov)
    assert abs(dr - (0.2 / (0.2 / np.sqrt(2)))) < 1e-9


def test_sequential_ortho_corr_below_limit() -> None:
    rng = np.random.default_rng(7)
    n = 400
    market = rng.normal(0, 0.01, n)
    raw = {
        "market": market.tolist(),
        "rates": (0.6 * market + rng.normal(0, 0.004, n)).tolist(),
        "credit": (0.4 * market + rng.normal(0, 0.005, n)).tolist(),
        "fx": rng.normal(0, 0.008, n).tolist(),
        "oil": (0.3 * market + rng.normal(0, 0.01, n)).tolist(),
        "size": rng.normal(0, 0.006, n).tolist(),
        "value": rng.normal(0, 0.006, n).tolist(),
        "momentum": rng.normal(0, 0.007, n).tolist(),
        "dividends": rng.normal(0, 0.005, n).tolist(),
    }
    ortho = sequential_orthogonalize(raw)
    assert pairwise_abs_corr(ortho) < 0.05


def test_synthetic_market_recovers_betas_and_shares() -> None:
    rng = np.random.default_rng(11)
    n = 500
    f = rng.normal(0, 0.01, size=(n, 3))
    true = np.array([0.80, -0.20, 0.35])
    y = f @ true + rng.normal(0, 0.001, n)
    names = ["market", "rates", "credit"]
    series = {names[i]: f[:, i].tolist() for i in range(3)}
    from app.services.factor_lens.betas import ridge_betas

    hats, r2 = ridge_betas(y.tolist(), series, names=names, ridge=1e-8)
    for i, name in enumerate(names):
        assert abs(hats[name] - true[i]) < 0.05
    shares = factor_variance_shares(hats, series, y.tolist())
    explained = sum(float(shares[n] or 0.0) for n in names) + float(shares["idiosyncratic"] or 0.0)
    assert abs(explained - 1.0) < 0.05
    assert r2 > 0.9


def test_portfolio_api_under_one_second() -> None:
    rebuild_from_fixture()
    uid = "u65"
    ensure_account(account_id="a65", user_id=uid, venue="e2e", mode="paper")
    rng = np.random.default_rng(3)
    for ticker in ("AAA", "BBB"):
        put_series(ticker, rng.normal(0, 0.01, 80).tolist())
        record_transaction(
            account_id="a65",
            user_id=uid,
            mode="paper",
            venue="e2e",
            external_id=f"t-{ticker}",
            kind="trade",
            instrument_id=ticker,
            ticker=ticker,
            qty="10",
            amount="1000",
            ccy="RUB",
            event_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
        )
    bind_session_user(uid)
    client = TestClient(app)
    client.get("/api/v1/factors/returns")
    started = perf_counter()
    res = client.get("/api/v1/portfolio/me/factors?mode=paper")
    elapsed = perf_counter() - started
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("enb") is not None or body.get("data_status") in {"ok", "частично", "нет данных"}
    inner = float(body.get("elapsed_ms") or 1e9) / 1000.0
    assert inner < 1.0
    assert elapsed < 2.5
    ret = client.get("/api/v1/factors/returns")
    assert ret.status_code == 200
    assert set(FACTOR_ORDER).issubset(set((ret.json().get("factors") or {}).keys()))


def test_style_long_short_and_momentum() -> None:
    from app.services.factor_lens.style import long_short_return, momentum_12_1

    chars = {f"T{i}": float(i) for i in range(9)}
    rets = {f"T{i}": 0.01 if i >= 6 else (-0.01 if i <= 2 else 0.0) for i in range(9)}
    ls = long_short_return(rets, chars)
    assert ls is not None and ls > 0
    hist = [0.0] * 231 + [0.01] * 21
    assert momentum_12_1(hist) is not None


def test_empty_store_is_no_data() -> None:
    bind_session_user("empty")
    client = TestClient(app)
    res = client.get("/api/v1/factors/returns")
    assert res.status_code == 200
    body = res.json()
    assert body["data_status"] == "нет данных"
    blob = str(body)
    assert "factor_returns" not in blob
    assert "fixture:65" not in blob
    assert "synthetic:65" not in blob


def test_factor_source_is_plain_language() -> None:
    rebuild_from_fixture()
    from app.services.factor_lens.store import snapshot

    body = snapshot()
    assert body["source"] == "оценка"
    blob = str(body)
    assert "fixture:65" not in blob
    assert "synthetic:65" not in blob
