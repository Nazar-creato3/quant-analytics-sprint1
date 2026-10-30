"""GA16-083: terminal provider health is not a public probe."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_terminal_health_requires_session() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/terminal/providers/health").status_code == 401
    assert client.get("/api/v1/terminal/data-health").status_code == 401
