"""Prompt 13: 12 historical + hypothetical + reverse stress."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.market_analysis.scenarios import apply_factor_shock
from app.services.qa.feature_flags import reset_for_tests
from app.services.risk_engine.series import put_series, reset as reset_series
from app.services.stress_library.service import (
    _reset,
    list_scenarios,
    reverse_stress,
    run_holdings,
)


def setup_function() -> None:
    reset_for_tests()
    _reset()
    reset_series()


def teardown_function() -> None:
    _reset()
    reset_series()
    reset_for_tests()


def _unit_beta() -> None:
    series = [0.02 if i % 2 == 0 else -0.01 for i in range(50)]
    put_series("SBER", series)
    put_series("IMOEX", series)


def test_catalog_has_twelve_historical():
    hist = [s for s in list_scenarios() if s["kind"] == "historical"]
    hypo = [s for s in list_scenarios() if s["kind"] == "hypothetical"]
    assert len(hist) == 12
    assert any(s["id"] == "1987" and s["limited_accuracy"] for s in hist)
    assert len(hypo) >= 9


def test_2020_matches_independent_and_legacy_shadow():
    _unit_beta()
    out = run_holdings([{"ticker": "SBER", "value": 10000, "ccy": "RUB"}])
    row = next(s for s in out["scenarios"] if s["id"] == "2020")
    independent = -0.34
    assert abs(row["pnl_pct"] - independent) < 1e-9
    assert row["pnl_rub"] == "-3400.00"
    legacy = apply_factor_shock({"market_beta": 1.0}, {"market_beta": -0.34})
    assert abs(legacy - row["pnl_pct"]) < 1e-9
    row22 = next(s for s in out["scenarios"] if s["id"] == "2022_us_rates")
    assert abs(row22["pnl_pct"] - (-0.19)) < 1e-9
    assert out["disclaimer"].startswith("Стресс-тест")
    assert "купите" not in out["disclaimer"].lower()


def test_reverse_and_limited_1987():
    _unit_beta()
    holdings = [{"ticker": "SBER", "value": 1000, "ccy": "RUB"}]
    rev = reverse_stress(holdings, targets=(-0.20,))
    assert rev[0]["market_shock"] is not None
    assert abs(rev[0]["market_shock"] - (-0.20)) < 0.05
    out = run_holdings(holdings)
    row = next(s for s in out["scenarios"] if s["id"] == "1987")
    assert row["limited_accuracy"] is True
    halt = next(s for s in out["scenarios"] if s["id"] == "halt_month")
    assert halt["pnl_pct"] is None  # unknown loss is not a zero loss


def test_api_empty_book():
    from app.tests.qa_session import bind_session_user, clear_session_user

    bind_session_user("nobody")
    client = TestClient(app)
    body = client.get("/api/v1/stress-library", params={"user_id": "nobody"}).json()
    clear_session_user()
    assert body["empty"] is True
    assert len(body["catalog"]) >= 21
    assert body["source"] == "stress_library"
