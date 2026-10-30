"""GA16-029: founder analytics is not public."""
from fastapi.testclient import TestClient

from app.main import app


def test_analytics_routes_need_a_session() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/analytics/plan").status_code == 401
    assert client.post("/api/v1/analytics/events", json={"name": "risk_view"}).status_code == 401
    assert client.get("/api/v1/analytics/metrics").status_code == 401
    assert client.get("/api/v1/analytics/weekly").status_code == 401
