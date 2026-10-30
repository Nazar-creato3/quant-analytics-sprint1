"""Tests for the multi-venue balance aggregator (mocked env + HTTP)."""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.portfolio import venue_balances as vb


def _patch_env(monkeypatch, env: dict[str, str]):
    def fake_value(key, default=None):
        val = env.get(key)
        return val if val is not None else default

    def fake_nonempty(*keys):
        return any((env.get(k) or "").strip() for k in keys)

    monkeypatch.setattr(vb, "env_value", fake_value)
    monkeypatch.setattr(vb, "env_nonempty", fake_nonempty)


class _FakeResponse:
    def __init__(self, status_code, json_data, text: str | None = None):
        self.status_code = status_code
        self._json = json_data
        self.text = text if text is not None else ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err",
                request=httpx.Request("GET", "https://example.test"),
                response=httpx.Response(
                    self.status_code,
                    json=self._json if isinstance(self._json, dict) else None,
                    text=self.text or None,
                ),
            )

    def json(self):
        if self._json is None and self.text:
            import json as _json

            return _json.loads(self.text)
        return self._json


class _FakeClient:
    response = None
    time_response = None
    last_headers = None
    last_url = None
    last_params = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        _FakeClient.last_headers = headers
        _FakeClient.last_url = url
        _FakeClient.last_params = params
        if isinstance(url, str) and url.endswith("/api/v3/time"):
            return _FakeClient.time_response or _FakeResponse(200, {"serverTime": 1_700_000_000_000})
        return _FakeClient.response


class TestStubVenues:
    def test_finam_pending_without_key(self, monkeypatch):
        _patch_env(monkeypatch, {})
        row = vb._finam_balance()
        assert row.configured is False
        assert row.mode == "pending"

    def test_finam_demo_with_key(self, monkeypatch):
        _patch_env(monkeypatch, {"FINAM_API_KEY": "tapi_sk_x"})
        row = vb._finam_balance()
        assert row.configured is True
        assert row.mode == "market_data"

    def test_tinkoff_platform_token_is_data_only(self, monkeypatch):
        _patch_env(monkeypatch, {"TINKOFF_API_TOKEN": "t.token"})
        row = vb._tinkoff_balance()
        assert row.configured is True
        assert row.mode == "market_data"
        assert row.refreshed is False  # no platform balance: accounts use user keys

    def test_stub_venues_not_refreshed(self, monkeypatch):
        _patch_env(monkeypatch, {"FINAM_API_KEY": "tapi_sk_x"})
        assert vb._finam_balance().refreshed is False


class TestBinance:
    async def test_pending_without_credentials(self, monkeypatch):
        _patch_env(monkeypatch, {})
        row = await vb._binance_balance()
        assert row.configured is False
        assert row.mode == "pending"

    async def test_parses_stablecoin_balance(self, monkeypatch):
        _patch_env(
            monkeypatch,
            {
                "BINANCE_API_KEY": "k",
                "BINANCE_API_SECRET": "s",
                "BINANCE_BASE_URL": "https://testnet.binance.vision",
            },
        )
        _FakeClient.response = _FakeResponse(
            200,
            {
                "balances": [
                    {"asset": "USDT", "free": "1000.0", "locked": "250.0"},
                    {"asset": "BTC", "free": "0.5", "locked": "0.0"},
                ]
            },
        )
        monkeypatch.setattr(vb.httpx, "AsyncClient", _FakeClient)

        row = await vb._binance_balance()
        assert row.configured is True
        assert row.mode == "testnet"
        assert row.refreshed is True  # live fetch actually happened
        assert row.balance_usd == 1000.0
        assert row.trading_usd == 250.0
        assert row.total_usd == 1250.0
        assert "non-stable" in row.detail
        assert _FakeClient.last_headers["X-MBX-APIKEY"] == "k"

    async def test_error_returns_configured_row(self, monkeypatch):
        _patch_env(
            monkeypatch,
            {"BINANCE_API_KEY": "k", "BINANCE_API_SECRET": "s"},
        )
        _FakeClient.response = _FakeResponse(
            401,
            {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."},
        )
        monkeypatch.setattr(vb.httpx, "AsyncClient", _FakeClient)

        row = await vb._binance_balance()
        assert row.configured is True
        assert row.error is not None
        assert "-2015" in row.error
        assert row.refreshed is False  # a failed fetch must not claim refreshed
        assert row.total_usd == 0.0
        assert "regenerate" in row.detail


class TestAggregate:
    async def test_totals_sum_across_venues(self, monkeypatch):
        _patch_env(
            monkeypatch,
            {
                "BINANCE_API_KEY": "k",
                "BINANCE_API_SECRET": "s",
                "BINANCE_BASE_URL": "https://testnet.binance.vision",
                "FINAM_API_KEY": "tapi_sk_x",
                "TINKOFF_API_TOKEN": "t.token",
            },
        )
        _FakeClient.response = _FakeResponse(
            200, {"balances": [{"asset": "USDT", "free": "100.0", "locked": "50.0"}]}
        )
        monkeypatch.setattr(vb.httpx, "AsyncClient", _FakeClient)

        out = await vb.build_venue_balances()
        assert {v.venue for v in out.venues} == {"binance", "finam", "tinkoff"}
        assert out.total_balance_usd == 100.0
        assert out.total_trading_usd == 50.0
        assert out.total_usd == 150.0
        assert out.as_of


class TestEndpoint:
    def test_balances_requires_auth(self):
        from app.api.v1.endpoints.portfolio import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/v1/portfolio/balances")
        assert resp.status_code in (401, 403, 422)
