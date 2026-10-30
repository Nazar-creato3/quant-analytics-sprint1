"""Prompt 21: sandbox / limits / calendar / digest. Flags default off."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.digest.service import preview, reset as reset_digest, set_prefs
from app.services.explanations.service import filter_wording
from app.services.instrument_calendar.service import events_for_user, reset as reset_cal, subscribe
from app.services.personal_limits.service import evaluate_limits, reset as reset_lim, set_limits, user_rule_reasons
from app.services.pretrade.policy import evaluate
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.risk_history.service import record_point, reset as reset_hist, series
from app.services.sandbox.service import compare, list_variants, reset as reset_sb, save_variant, simulate
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    reset_sb()
    reset_lim()
    reset_cal()
    reset_digest()
    reset_hist()


def teardown_function() -> None:
    reset_sb()
    reset_lim()
    reset_cal()
    reset_digest()
    reset_hist()
    reset_for_tests()
    clear_session_user()


def test_flags_off_hide_api():
    bind_session_user("u")
    client = TestClient(app)
    assert client.post("/api/v1/sandbox/simulate", json={"user_id": "u"}).status_code == 404
    assert client.get("/api/v1/personal-limits", params={"user_id": "u"}).status_code == 404
    assert client.get("/api/v1/instrument-calendar", params={"user_id": "u"}).status_code == 404
    assert client.get("/api/v1/digest", params={"user_id": "u"}).status_code == 404


def test_sandbox_recalc_and_variant():
    set_global("qa_sandbox", True)
    out = simulate(user_id="u-sb", holdings=[{"ticker": "SBER", "qty": "10", "price": "1", "ccy": "RUB"}])
    assert out["source"] == "sandbox"
    assert out["elapsed_ms"] < 2000
    assert filter_wording(out["disclaimer"]) == []
    assert "купи" not in out["disclaimer"].lower()
    saved = save_variant(user_id="u-sb", name="a", payload=out)
    assert saved["n"] == 1
    assert list_variants(user_id="u-sb")
    assert compare(user_id="u-sb")["data_status"] == "ok"
    bind_session_user("u-sb")
    client = TestClient(app)
    body = client.post("/api/v1/sandbox/simulate", json={"user_id": "u-sb", "holdings": [{"ticker": "SBER", "qty": "1"}]}).json()
    assert body["source"] == "sandbox"


def test_limits_enter_gate_and_empty_calendar():
    set_global("qa_personal_limits", True)
    set_global("qa_calendar", True)
    set_limits(user_id="u-lim", crisis_loss=0.0, concentration=0.0, leverage=0.0, drawdown=0.0)
    ev = evaluate_limits(user_id="u-lim", mode="paper")
    assert ev["data_status"] == "ok"
    reasons = user_rule_reasons(user_id="u-lim", mode="paper")
    dec = evaluate(kind="bot", actor="auto", user_id="u-lim", ticker="SBER", qty=1, price=10, mode="paper")
    assert dec.verdict in {"block", "warn", "ok"}
    if reasons:
        assert any(r.code == "personal_limit" for r in dec.reasons)
    cal = events_for_user(user_id="u-lim")
    assert cal["data_status"] == "нет данных"
    assert cal["events"] == []
    sub = subscribe(user_id="u-lim", ticker="SBER")
    assert "SBER" in sub["tickers"]


def test_digest_preview_no_delivery():
    set_global("qa_digest", True)
    set_global("qa_sandbox", True)
    prefs = set_prefs(user_id="u-d", cadence="weekly", channel="telegram")
    assert prefs["delivery"] is False
    record_point(user_id="u-d", var_95=0.1, hhi=0.2, twr="0")
    hist = series(user_id="u-d")
    assert hist["data_status"] == "ok"
    out = preview(user_id="u-d", mode="paper")
    assert out["delivery"] is False
    assert out["first_screen"]["data_status"] in {"нет данных", "ok"}
    bind_session_user("u-d")
    client = TestClient(app)
    assert client.get("/api/v1/digest", params={"user_id": "u-d"}).status_code == 200
