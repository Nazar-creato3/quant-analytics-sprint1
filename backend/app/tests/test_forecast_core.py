"""Prompt 11: one forecast() for UI and chat; horizon gate; public accuracy."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.forecast_core.service import for_chat, for_market, for_ui
from app.services.forecast_log.store import get_store
from app.services.qa.feature_flags import reset_for_tests
from app.services.risk_engine.series import put_series, reset as reset_series
from app.tests.qa_session import bind_session_user, clear_session_user


def setup_function() -> None:
    reset_for_tests()
    reset_series()
    get_store().reset()
    clear_session_user()


def teardown_function() -> None:
    reset_series()
    reset_for_tests()
    clear_session_user()


def test_ui_and_chat_same_numbers():
    put_series("SBER", [0.01, 0.02, -0.005, 0.012, 0.008])
    ui = for_ui("SBER")
    chat = for_chat("SBER")
    market = for_market("SBER")
    assert ui["direction"] == chat["direction"] == market["direction"]
    assert ui["probability"] == chat["probability"] == market["probability"]
    assert ui["asset_id"] == chat["asset_id"]
    assert ui["source"] == "forecast_core"
    assert any(c["name"] == "stacking" and c["available"] is False for c in ui["components"])


def test_api_and_public_accuracy():
    client = TestClient(app)
    assert client.get("/api/v1/forecast-core", params={"ticker": "SBER"}).status_code == 401
    assert client.get("/api/v1/forecast-accuracy").status_code in (401, 403)
    bind_session_user("u1")
    body = client.get("/api/v1/forecast-core", params={"ticker": "SBER"}).json()
    assert body["ticker"] == "SBER"
    acc = client.get("/api/v1/forecast-accuracy").json()
    assert acc["public"] is True
    assert "наивн" in acc["methodology"].lower()
    assert "flag" not in str(body).lower()
    assert "flag" not in str(acc).lower()
