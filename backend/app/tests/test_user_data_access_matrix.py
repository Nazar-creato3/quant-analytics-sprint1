"""E46-04 tail: every user-data route is 401 without session and 403 on foreign id."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tests.qa_session import auth_headers

GET_USER_DATA = (
    "/api/v1/returns",
    "/api/v1/risk",
    "/api/v1/report",
    "/api/v1/privacy/export",
    "/api/v1/behavior",
    "/api/v1/concentration",
    "/api/v1/stress-library",
    "/api/v1/book/positions",
    "/api/v1/act/profile",
    "/api/v1/act/journal",
    "/api/v1/investment-profile",
    "/api/v1/onboarding/status",
    "/api/v1/notifications",
    "/api/v1/notifications/telegram/code",
    "/api/v1/risk/backtests",
    "/api/v1/risk/shadow",
    "/api/v1/qa-tools/journal",
    "/api/v1/personal-limits",
    "/api/v1/account",
    "/api/v1/deal-intents",
    "/api/v1/grid",
    "/api/v1/dca",
)

POST_USER_DATA = (
    ("/api/v1/risk-gate/preview", {"user_id": "victim", "ticker": "SBER", "qty": 1, "price": 10}),
    ("/api/v1/privacy/erase", None),
    ("/api/v1/qa-tools/invoke", {"name": "qa_portfolio_report", "user_id": "victim"}),
    ("/api/v1/act/propose", None),
    ("/api/v1/onboarding/demo", None),
)


def test_unauthenticated_user_data_is_401():
    client = TestClient(app)
    for path in GET_USER_DATA:
        res = client.get(path, params={"user_id": "victim", "mode": "paper"})
        assert res.status_code == 401, (path, res.status_code)
    for path, body in POST_USER_DATA:
        res = client.post(path, params={"user_id": "victim"}, json=body)
        assert res.status_code == 401, (path, res.status_code)


def test_foreign_query_is_403_on_session_routes():
    client = TestClient(app)
    headers = auth_headers("alice")
    for path in (
        "/api/v1/returns",
        "/api/v1/risk",
        "/api/v1/report",
        "/api/v1/privacy/export",
        "/api/v1/behavior",
        "/api/v1/concentration",
        "/api/v1/stress-library",
        "/api/v1/act/journal",
        "/api/v1/investment-profile",
        "/api/v1/onboarding/status",
        "/api/v1/notifications",
        "/api/v1/notifications/telegram/code",
        "/api/v1/risk/backtests",
        "/api/v1/risk/shadow",
        "/api/v1/qa-tools/journal",
    ):
        res = client.get(path, params={"user_id": "bob", "mode": "paper"}, headers=headers)
        assert res.status_code == 403, (path, res.status_code)
    preview = client.post(
        "/api/v1/risk-gate/preview",
        json={"user_id": "bob", "ticker": "SBER", "qty": 1, "price": 10},
        headers=headers,
    )
    assert preview.status_code == 403


def test_no_raw_query_user_id_left_in_qa_endpoints():
    root = Path(__file__).resolve().parents[1] / "api" / "v1" / "endpoints"
    leftovers: list[str] = []
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "user_id: str = Query(" in text:
            leftovers.append(str(path.relative_to(root.parent.parent.parent)))
    assert leftovers == []
