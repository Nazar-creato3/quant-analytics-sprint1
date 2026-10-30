"""Prompt 11B: leakage detector, validation card, registry API."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.model_risk.math import detect_lookahead, psi
from app.services.model_risk.service import validate_heuristic
from app.services.qa.feature_flags import reset_for_tests
from app.services.risk_engine.series import put_series, reset as reset_series
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    reset_series()
    clear_session_user()


def teardown_function() -> None:
    reset_for_tests()
    reset_series()
    clear_session_user()


def test_lookahead_detector_catches_future_feature():
    realized = [((i * 17) % 10 - 4.5) / 100.0 for i in range(40)]
    leaky = realized[1:] + [0.0]
    assert detect_lookahead(leaky, realized) is True
    assert detect_lookahead(realized, realized) is False


def test_validation_report_marks_beta_without_naive_edge():
    report = validate_heuristic([0.01, -0.01] * 40)
    assert report["lookahead_injected_detected"] is True
    assert report["card"].endswith(".md")
    assert "brier" in report
    assert report["status"] in {"beta", "ready"}


def test_status_without_session_is_401():
    client = TestClient(app)
    assert client.get("/api/v1/model-risk/status").status_code == 401


def test_status_without_series_is_no_data():
    """GA16-037: missing SBER series must not invent a Brier from a baked-in path."""
    client = TestClient(app)
    bind_session_user("u1")
    empty = validate_heuristic()
    assert empty["brier"] is None
    assert empty["status"] == "нет данных"
    body = client.get("/api/v1/model-risk/status").json()
    assert body["validation"]["brier"] is None
    assert body["user_reason"] == "нет данных"
    assert "синтетик" not in str(body).lower()


def test_psi_and_api():
    assert psi([0.0, 0.1, 0.2] * 10, [0.8, 0.9, 1.0] * 10) > 0
    put_series("SBER", [0.01, -0.005, 0.002, 0.004, -0.003, 0.001] * 20)
    bind_session_user("u1")
    client = TestClient(app)
    body = client.get("/api/v1/model-risk/status").json()
    assert body["registry"][0]["role"] == "champion"
    assert any(x["model_id"] == "stacking" and x["available"] is False for x in body["registry"])
    assert body["validation"]["lookahead_injected_detected"] is True
    assert body["validation"]["brier"] is not None
