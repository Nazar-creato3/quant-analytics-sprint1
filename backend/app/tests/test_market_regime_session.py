"""GA16-323: market regime requires a session and hides flag names."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.market_regime import router
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.tests.qa_session import auth_headers


def setup_function() -> None:
    reset_for_tests()


def teardown_function() -> None:
    reset_for_tests()


def test_anonymous_cannot_read_regime() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/regime")
    assert resp.status_code in (401, 403)


def test_flag_off_hides_internal_name() -> None:
    set_global("qa_market_regime", False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/regime", headers=auth_headers("user-1"))
    assert resp.status_code == 404
    assert "flag" not in resp.text.lower()
    assert "qa_market" not in resp.text.lower()
