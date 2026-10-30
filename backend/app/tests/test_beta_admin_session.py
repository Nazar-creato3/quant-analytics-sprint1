"""Beta admin HTTP is session-bound (AUD-Мозг-41)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.beta_admin import router
from app.services.beta_admin.service import (
    add_user_for_tests,
    register_actor_for_tests,
    reset_beta_admin,
)
from app.services.qa.feature_flags import reset_for_tests
from app.tests.qa_session import auth_headers


def setup_function() -> None:
    reset_for_tests()
    reset_beta_admin()


def teardown_function() -> None:
    reset_for_tests()
    reset_beta_admin()


def test_anonymous_cannot_read_beta_admin() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as client:
        health = client.get("/api/v1/beta-admin/health", params={"actor_id": "owner"})
        users = client.post("/api/v1/beta-admin/users", json={"actor_id": "owner"})
    assert health.status_code in (401, 403)
    assert users.status_code in (401, 403)


def test_body_actor_id_cannot_impersonate() -> None:
    register_actor_for_tests(actor_id="owner", role="founder", mfa=True)
    add_user_for_tests(user_id="secret-user", status="active")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as client:
        users = client.post(
            "/api/v1/beta-admin/users",
            json={"actor_id": "owner"},
            headers=auth_headers("stranger"),
        )
    assert users.status_code == 200
    body = users.json()
    assert "secret-user" not in str(body)
