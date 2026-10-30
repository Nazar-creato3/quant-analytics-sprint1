"""Experiment HTTP ignores posted subject (AUD-Мозг-42)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.experiments import router
from app.services.experiments.service import reset_experiments, set_founder_decision_for_tests
from app.services.qa.feature_flags import reset_for_tests
from app.tests.qa_session import auth_headers


def setup_function() -> None:
    reset_for_tests()
    reset_experiments()


def teardown_function() -> None:
    reset_for_tests()
    reset_experiments()


def test_anonymous_cannot_assign_experiment() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as client:
        status = client.get("/api/v1/experiments/status")
        assigned = client.post("/api/v1/experiments/assign", json={"subject": "victim"})
    assert status.status_code in (401, 403)
    assert assigned.status_code in (401, 403)


def test_assign_uses_session_not_body_subject() -> None:
    import os

    os.environ["FF_QA_EXPERIMENTS"] = "1"
    set_founder_decision_for_tests({"name": "copy", "split": 50})
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as client:
        assigned = client.post(
            "/api/v1/experiments/assign",
            json={"subject": "foreign-subject"},
            headers=auth_headers("session-user"),
        )
    assert assigned.status_code == 200
    body = assigned.json()
    assert "foreign-subject" not in str(body)
    assert "subject_pseudo" not in body
