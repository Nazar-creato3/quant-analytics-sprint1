"""Baseline letter б: T-Invest sandbox account path without founder live keys."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tests.qa_session import auth_headers
from app.services.integration.historical_data import tinkoff_rest_base, tinkoff_use_sandbox
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.venue_adapters.tbank import SANDBOX_HOST, connect_preview, host


FIXTURE = Path(__file__).parent / "fixtures" / "venues" / "tbank_operations.json"


@pytest.fixture(autouse=True)
def _reset():
    reset_for_tests()
    get_book().reset()
    set_global("qa_venue_adapters", True)
    set_global("qa_portfolio_book", True)
    yield
    get_book().reset()
    reset_for_tests()


def test_letter_b_default_preview_uses_sandbox_host_and_paper_book() -> None:
    ops = json.loads(FIXTURE.read_text(encoding="utf-8"))
    preview = connect_preview(
        user_id="baseline-b",
        scopes=["read"],
        operations=ops,
        readonly=True,
        sandbox=True,
    )
    assert preview["sandbox"] is True
    assert preview["host"] == SANDBOX_HOST
    assert preview["host"].startswith("sandbox-")
    assert preview["accounts"][0]["mode"] == "paper"
    assert preview["trade_enabled"] is False
    pos = get_book().positions(user_id="baseline-b", mode="paper")
    assert pos
    assert all(p.ticker for p in pos)


def test_letter_b_prod_host_never_selected_for_sandbox_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TINKOFF_SANDBOX", "true")
    assert tinkoff_use_sandbox() is True
    assert tinkoff_rest_base() == "sandbox-invest-public-api.tbank.ru"
    assert host(sandbox=True) == SANDBOX_HOST
    assert "sandbox-" not in host(sandbox=False)


def test_letter_b_api_preview_defaults_sandbox_without_live_token() -> None:
    client = TestClient(app)
    ops = json.loads(FIXTURE.read_text(encoding="utf-8"))
    res = client.post(
        "/api/v1/venues/tbank/preview",
        json={"scopes": ["read"], "operations": ops, "sandbox": True},
        headers=auth_headers("baseline-b-api"),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["host"].startswith("sandbox-")
    assert body.get("sandbox") is True
    assert body["accounts"][0]["mode"] == "paper"
