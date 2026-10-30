"""GA16-332: risk API hides flags, exceptions, and as_of_source."""
from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.risk_engine import router
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.qa.session_user import require_session_user_id


def setup_function() -> None:
    reset_for_tests()


def teardown_function() -> None:
    reset_for_tests()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_session_user_id] = lambda: "risk-user"
    return TestClient(app, raise_server_exceptions=False)


def test_flag_off_hides_internal_name() -> None:
    set_global("qa_risk_engine", False)
    with _client() as client:
        resp = client.get("/api/v1/risk")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Нет данных"
    assert "flag" not in resp.text.lower()


def test_compute_error_hides_exception_and_source() -> None:
    with patch(
        "app.api.v1.endpoints.risk_engine.compute_risk_for_user",
        side_effect=RuntimeError("table risk_engine missing"),
    ):
        with _client() as client:
            resp = client.get("/api/v1/risk")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Нет данных"
    assert "risk_engine" not in resp.text.lower()
    assert "table" not in resp.text.lower()


def test_what_if_omits_as_of_source() -> None:
    with patch(
        "app.api.v1.endpoints.risk_engine.compute_what_if",
        return_value={"persisted": False, "nav": "0"},
    ):
        with _client() as client:
            resp = client.post(
                "/api/v1/risk/what-if",
                json={"holdings": [{"ticker": "SBER", "qty": "1", "price": "100"}]},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert "as_of_source" not in body
    assert "elapsed_ms" in body
