"""Prompt 12: one regime for market and instrument; event on flip."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.event_bus.bus import get_bus
from app.services.event_bus.notifications import circuit_state, reset_side_effects
from app.services.market_regime.service import _reset, classify, snapshot, to_composer_regime
from app.services.pretrade.policy import evaluate
from app.services.qa.feature_flags import reset_for_tests
from app.services.risk_engine.series import put_series, reset as reset_series
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    _reset()
    reset_series()
    get_bus().reset()
    reset_side_effects()
    clear_session_user()


def teardown_function() -> None:
    _reset()
    reset_series()
    get_bus().reset()
    reset_side_effects()
    reset_for_tests()
    clear_session_user()


def _crisis_returns() -> list[float]:
    return [0.06 if i % 2 == 0 else -0.09 for i in range(20)]


def test_labels_and_same_day_consistency():
    up = [0.004] * 20
    a = classify(up, scope="instrument", ticker="SBER")
    b = classify(up, scope="instrument", ticker="SBER")
    assert a["label"] == b["label"] == "trend_up"
    assert a["source"] == "market_regime"
    assert a["scope"] == "instrument"
    down = [-0.05] * 12
    crisis = classify(down, scope="market", ticker="IMOEX")
    assert crisis["label"] in {"crisis", "volatility", "trend_down"}
    assert to_composer_regime("volatility") == "high_vol"


def test_chat_and_api_same_snapshot():
    put_series("IMOEX", [0.003] * 25)
    put_series("SBER", [0.003] * 25)
    snap = snapshot(ticker="SBER")
    bind_session_user("regime-user")
    client = TestClient(app)
    body = client.get("/api/v1/regime", params={"ticker": "SBER"}).json()
    assert body["market"]["label"] == snap["market"]["label"]
    assert body["instrument"]["label"] == snap["instrument"]["label"]
    assert body["market"]["scope"] == "market"
    assert body["instrument"]["scope"] == "instrument"


def test_regime_changed_event():
    classify([0.004] * 20, scope="market", ticker="IMOEX")
    classify([-0.05] * 12, scope="market", ticker="IMOEX")
    names = [e.name for e in get_bus()._stream]
    assert "regime.changed" in names


def test_empty_series_is_insufficient_not_range():
    empty = classify([], scope="market", ticker="IMOEX")
    assert empty["label"] == "insufficient"
    assert empty["status"] == "insufficient_data"
    assert empty["data_status"] == "нет данных"
    assert empty["explain"] == "нет данных"
    assert to_composer_regime("insufficient") == "unknown"
    short = classify([0.01] * 3, scope="instrument", ticker="SBER")
    assert short["label"] != "range"


def test_crisis_pauses_bots_and_blocks_auto():
    classify([0.004] * 20, scope="market", ticker="IMOEX")
    crisis = classify(_crisis_returns(), scope="market", ticker="IMOEX")
    assert crisis["label"] == "crisis"
    assert "regime-crisis" in circuit_state()["paused_bots"]
    put_series("SBER", _crisis_returns())
    auto = evaluate(
        kind="bot",
        actor="auto",
        user_id="u-reg",
        ticker="SBER",
        qty=1,
        price=10,
        nav=100_000,
    )
    assert auto.verdict == "block"
    assert any(r.code == "regime_crisis" for r in auto.reasons)
