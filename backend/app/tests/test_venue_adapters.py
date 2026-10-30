"""Prompt 06: venue registry, withdraw reject, T-Bank isolation, book ingest."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.main import app
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests
from app.tests.qa_session import auth_headers
from app.services.venue_adapters.errors import WithdrawKeyRejected
from app.services.venue_adapters.key_check import assert_not_logged, inspect_key_permissions, redact_secret
from app.services.venue_adapters.registry import get_venue, list_venues
from app.services.venue_adapters.tbank import PROD_HOST, SANDBOX_HOST, connect_preview, grpc_metadata, isolate_tokens


@pytest.fixture(autouse=True)
def _reset():
    reset_for_tests()
    get_book().reset()
    yield
    get_book().reset()
    reset_for_tests()


def test_registry_has_core_venues():
    ids = {v.id for v in list_venues()}
    assert {"tbank", "finam", "binance", "bybit", "mexc", "bcs"} <= ids
    assert get_venue("tinkoff").id == "tbank"
    assert get_venue("bcs").support == "unsupported"


def test_withdraw_key_rejected():
    with pytest.raises(WithdrawKeyRejected):
        inspect_key_permissions("binance", ["trade", "enableWithdrawals"])
    with pytest.raises(WithdrawKeyRejected):
        inspect_key_permissions("tbank", ["read", "transfer"])
    ok = inspect_key_permissions("tbank", ["read", "trade"])
    assert ok.can_trade is True
    assert ok.withdraw is False


def test_secret_not_in_logs():
    secret = "super-secret-token-value"
    assert secret not in redact_secret(secret)
    assert_not_logged({"app": "QuantAnalytics", "token": redact_secret(secret)}, secret)
    with pytest.raises(AssertionError):
        assert_not_logged({"token": secret}, secret)


def test_tbank_app_name_and_hosts():
    assert Settings.model_fields["TINKOFF_APP_NAME"].default == "QuantAnalytics"
    meta = dict(grpc_metadata(user_token="user-aaa"))
    assert meta["x-app-name"] == settings.TINKOFF_APP_NAME
    assert meta["authorization"] == "Bearer user-aaa"
    assert SANDBOX_HOST.startswith("sandbox-")
    assert PROD_HOST == "invest-public-api.tbank.ru:443"


def test_user_token_isolation():
    isolate_tokens("platform", "user-a", "user-b")
    with pytest.raises(ValueError):
        isolate_tokens("same", "same", "other")
    with pytest.raises(ValueError):
        isolate_tokens("p", "dup", "dup")


def test_tbank_preview_writes_book():
    ops = json.loads((Path(__file__).parent / "fixtures" / "venues" / "tbank_operations.json").read_text())
    preview = connect_preview(user_id="u1", scopes=["read", "trade"], operations=ops, readonly=False)
    assert preview["synced"] == 2
    assert preview["trade_enabled"] is False
    assert preview["app_name"] == settings.TINKOFF_APP_NAME
    assert preview["sandbox"] is True
    assert preview["accounts"][0]["mode"] == "paper"
    pos = get_book().positions(user_id="u1", mode="paper")
    assert pos[0].ticker == "SBER"
    from decimal import Decimal

    assert pos[0].qty == Decimal("10")


def test_venues_api_and_withdraw_http():
    client = TestClient(app)
    listed = client.get("/api/v1/venues")
    assert listed.status_code == 200
    assert any(v["id"] == "tbank" for v in listed.json()["venues"])
    anon = client.post(
        "/api/v1/venues/tbank/preview",
        json={"user_id": "u2", "scopes": ["withdraw"], "operations": []},
    )
    assert anon.status_code == 401
    bad = client.post(
        "/api/v1/venues/tbank/preview",
        json={"user_id": "u2", "scopes": ["withdraw"], "operations": []},
        headers=auth_headers("u2"),
    )
    assert bad.status_code == 400
    assert "вывод" in bad.json()["detail"].lower() or "Withdraw" in bad.json()["detail"]


def test_tbank_preview_http_ignores_foreign_user_id():
    ops = json.loads((Path(__file__).parent / "fixtures" / "venues" / "tbank_operations.json").read_text())
    client = TestClient(app)
    resp = client.post(
        "/api/v1/venues/tbank/preview",
        json={"user_id": "bob", "scopes": ["read", "trade"], "operations": ops},
        headers=auth_headers("alice"),
    )
    assert resp.status_code == 200
    assert get_book().positions(user_id="bob", mode="paper") == []
    alice_pos = get_book().positions(user_id="alice", mode="paper")
    assert alice_pos and alice_pos[0].ticker == "SBER"
