"""E46-04: /returns /risk /report use session identity, not a spoofable query."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app


def _auth(user_id: str) -> dict[str, str]:
    token = create_access_token(user_id, extra_claims={"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


def test_unauthenticated_portfolio_reads_are_401():
    client = TestClient(app)
    for path in ("/api/v1/returns", "/api/v1/risk", "/api/v1/report", "/api/v1/report/pdf"):
        res = client.get(path, params={"user_id": "victim"})
        assert res.status_code == 401, path


def test_query_user_id_mismatch_is_403():
    client = TestClient(app)
    headers = _auth("alice")
    for path in ("/api/v1/returns", "/api/v1/risk", "/api/v1/report"):
        res = client.get(path, params={"user_id": "bob"}, headers=headers)
        assert res.status_code == 403, path
        assert "session" in res.json()["detail"]


def test_session_user_sees_own_empty_book():
    client = TestClient(app)
    headers = _auth("alice")
    ret = client.get("/api/v1/returns", params={"user_id": "alice"}, headers=headers)
    assert ret.status_code == 200
    assert ret.json()["data_status"] == "нет данных"
    risk = client.get("/api/v1/risk", headers=headers)
    assert risk.status_code == 200
    assert risk.json()["data_status"] == "нет данных"
    report = client.get("/api/v1/report", headers=headers)
    assert report.status_code == 200
    first = report.json().get("first_screen") or {}
    assert first.get("data_status") == "нет данных" or report.json().get("demo") is True


def test_demo_placeholder_resolves_to_session_user():
    """The UI sends user_id=demo before it knows the session; that must not 403."""
    client = TestClient(app)
    headers = _auth("alice")
    for path in ("/api/v1/returns", "/api/v1/risk", "/api/v1/report"):
        res = client.get(path, params={"user_id": "demo"}, headers=headers)
        assert res.status_code == 200, path
