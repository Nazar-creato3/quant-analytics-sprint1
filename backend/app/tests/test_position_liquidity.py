from math import exp, log, sqrt

from fastapi.testclient import TestClient

from app.main import app
from app.services.legal.catalog import load_ui_texts, reset_cache
from app.services.position_liquidity.math import corwin_schultz_spread, days_to_exit, square_root_impact
from app.services.position_liquidity.service import portfolio_liquidity
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_position_liquidity", True)


def teardown_function() -> None:
    reset_for_tests()
    clear_session_user()


def test_hand_days_and_impact() -> None:
    # Q=1_000_000, ADV=10_000_000, part=0.1 → days = 1e6 / 1e6 = 1
    assert days_to_exit(1_000_000, 10_000_000, 0.1) == 1.0
    # impact = 1 * 0.02 * sqrt(0.1) = 0.0063245
    imp = square_root_impact(position_value=1_000_000, adv=10_000_000, sigma_daily=0.02)
    assert imp is not None
    assert abs(imp - 0.02 * (0.1**0.5)) < 1e-9


def test_corwin_schultz_one_bar_not_mid_range() -> None:
    # H=101, L=99. Relative range (H-L)/mid = 0.02. Corwin–Schultz is larger.
    spread = corwin_schultz_spread(101.0, 99.0)
    assert spread is not None
    b = log(101.0 / 99.0) ** 2
    alpha = (sqrt(2.0 * b) - sqrt(b)) / (3.0 - 2.0 * sqrt(2.0))
    expected = 2.0 * (exp(alpha) - 1.0) / (1.0 + exp(alpha))
    assert abs(spread - expected) < 1e-12
    assert abs(spread - 0.02) > 0.01
    assert corwin_schultz_spread(100.0, 100.0) == 0.0
    assert corwin_schultz_spread(99.0, 101.0) is None


def test_no_adv_is_label_not_zero() -> None:
    assert days_to_exit(100, None, 0.1) is None
    book = portfolio_liquidity("u", "synth", 0.1)
    illiq = next(r for r in book["issues"] if r["ticker"] == "ILLIQ")
    assert illiq["status"] == "нет сделок"
    assert illiq["days_to_exit"] is None
    assert "редкие сделки" in illiq["flags"]


def test_http_and_texts() -> None:
    bind_session_user("u-64")
    client = TestClient(app)
    r = client.get("/api/v1/portfolio/paper/liquidity", params={"participation": 0.1})
    assert r.status_code == 200
    body = r.json()
    assert body["data_status"] == "нет данных"
    assert body["issues"] == []
    assert "ISS" not in str(body.get("source"))
    assert "SBER" not in str(body["issues"])
    reset_cache()
    blob = " ".join(str(v).lower() for v in load_ui_texts()["liquidity"].values())
    assert "стоит продать" not in blob
