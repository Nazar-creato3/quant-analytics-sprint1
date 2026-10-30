"""GA16-360: legal status/docs must not expose catalog errors, path, or sha256."""
from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.legal import router


def test_legal_status_hides_catalog_errors():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    with patch(
        "app.api.v1.endpoints.legal.validate_catalog",
        return_value=["path=/secret/legal.md sha256=deadbeef"],
    ):
        resp = client.get("/api/v1/legal/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["catalog_ok"] is False
    assert "catalog_errors" not in body
    blob = str(body).lower()
    assert "sha256" not in blob
    assert "path=" not in blob
    assert "deadbeef" not in blob


def test_legal_document_hides_path_and_hash():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    fake = {
        "code": "terms",
        "version": "1",
        "effective_date": "2026-01-01",
        "status": "active",
        "approved_by": "legal",
        "sha256": "abc123",
        "body": "текст",
        "path": "/app/legal/terms/1.md",
    }
    with patch("app.api.v1.endpoints.legal.get_document", return_value=fake):
        resp = client.get("/api/v1/legal/terms")
    assert resp.status_code == 200
    body = resp.json()
    assert "sha256" not in body
    assert "path" not in body
    assert body["body"] == "текст"
