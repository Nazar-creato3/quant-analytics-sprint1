"""Prompt 22: typed chat tools from core, no order tools."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.chat.qa_registry import FORBIDDEN, catalog, invoke, journal, reset
from app.services.portfolio_report.service import assemble
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()
    reset()


def teardown_function() -> None:
    reset()
    reset_for_tests()


def test_report_tool_matches_assemble():
    report = assemble(user_id="nobody")
    out = invoke(name="qa_portfolio_report", user_id="nobody")
    assert out["first_screen"]["var_95"] == report["first_screen"]["var_95"]
    assert out["first_screen"]["hhi"] == report["first_screen"]["hhi"]
    assert journal()


def test_order_tools_forbidden():
    client = TestClient(app)
    for name in FORBIDDEN:
        try:
            invoke(name=name, user_id="u")
            raise AssertionError("should block")
        except PermissionError:
            pass
        from app.tests.qa_session import bind_session_user, clear_session_user

        bind_session_user("u")
        resp = client.post("/api/v1/qa-tools/invoke", json={"name": name, "user_id": "u"})
        assert resp.status_code == 403
        clear_session_user()
    anon = client.get("/api/v1/qa-tools")
    assert anon.status_code == 401
    from app.tests.qa_session import bind_session_user, clear_session_user

    bind_session_user("u")
    listed = client.get("/api/v1/qa-tools").json()
    titles = {t["title"] for t in listed["tools"]}
    assert "Отчёт портфеля" in titles
    assert all("qa_" not in t["title"] for t in listed["tools"])
    assert "forbidden" not in listed
    assert catalog()
    clear_session_user()


def test_search_and_prepare_no_order():
    from app.tests.qa_session import bind_session_user, clear_session_user

    client = TestClient(app)
    assert client.get("/api/v1/qa-tools/search", params={"q": "риск"}).status_code == 401
    bind_session_user("u")
    found = client.get("/api/v1/qa-tools/search", params={"q": "риск"}).json()
    assert found["items"]
    labels = " ".join(i["label"] for i in found["items"])
    assert "Composer" not in labels
    assert "qa_" not in labels
    clear_session_user()
    prep = invoke(name="qa_prepare_risk_check", ticker="SBER")
    assert prep["creates_order"] is False
    assert "portfolio-risk" in prep["next"]
