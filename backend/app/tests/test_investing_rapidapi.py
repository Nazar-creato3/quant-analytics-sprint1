"""Tests for the Investing.com RapidAPI provider (mocked HTTP, no live key)."""
from __future__ import annotations

import httpx
import pytest

from app.services.data import investing_rapidapi as inv


class _FakeResponse:
    def __init__(self, status_code: int, json_data):
        self.status_code = status_code
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("GET", "https://example.test"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._json


class _FakeClient:
    """Records the last request and returns a queued response."""

    last_request: dict = {}
    queued: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None, headers=None):
        _FakeClient.last_request = {"url": url, "params": params, "headers": headers}
        if _FakeClient.queued:
            return _FakeClient.queued.pop(0)
        return _FakeResponse(200, {})


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(inv.settings, "RAPIDAPI_KEY", "test-key")
    monkeypatch.setattr(inv.settings, "INVESTING_RAPIDAPI_ENABLED", True)
    monkeypatch.setattr(
        inv.settings, "INVESTING_RAPIDAPI_HOST", "investing-com-ultimate-api.p.rapidapi.com"
    )
    return inv.settings


@pytest.fixture
def fake_http(monkeypatch):
    _FakeClient.last_request = {}
    _FakeClient.queued = []
    monkeypatch.setattr(inv.httpx, "AsyncClient", _FakeClient)
    return _FakeClient


class TestConfig:
    def test_not_configured_without_key(self, monkeypatch):
        monkeypatch.setattr(inv.settings, "RAPIDAPI_KEY", "")
        assert inv.is_configured() is False

    def test_configured_with_key(self, configured):
        assert inv.is_configured() is True


class TestPureHelpers:
    def test_as_list_variants(self):
        assert inv._as_list([{"a": 1}]) == [{"a": 1}]
        assert inv._as_list({"data": [{"a": 1}]}, "data") == [{"a": 1}]
        assert inv._as_list({"x": [{"b": 2}]}) == [{"b": 2}]  # first list fallback
        assert inv._as_list(None) == []
        assert inv._as_list("nope") == []

    def test_impact_to_effect_direction(self):
        assert inv._impact_to_effect("high", forecast=3.0, previous=2.0) > 0
        assert inv._impact_to_effect("high", forecast=1.0, previous=2.0) < 0
        assert inv._impact_to_effect("high") == 0.0  # no delta -> neutral direction

    def test_normalize_event(self):
        row = {
            "event": "US CPI",
            "importance": "high",
            "forecast": "3.2%",
            "previous": "3.0%",
            "country": "US",
            "date": "2026-07-15T12:30:00Z",
        }
        ev = inv._normalize_event(row)
        assert ev["event_name"] == "US CPI"
        assert ev["impact"] == "high"
        assert ev["source"] == "investing_rapidapi"
        assert ev["market_effect"] > 0
        assert ev["confidence"] == 0.8


class TestFetchers:
    async def test_get_returns_none_when_unconfigured(self, monkeypatch, fake_http):
        monkeypatch.setattr(inv.settings, "RAPIDAPI_KEY", "")
        result = await inv._get("/economic-calendar/")
        assert result is None
        assert _FakeClient.last_request == {}  # no HTTP performed

    async def test_get_sends_rapidapi_headers(self, configured, fake_http):
        _FakeClient.queued = [_FakeResponse(200, {"data": []})]
        await inv._get("/economic-calendar/", params={"country": "US"})
        headers = _FakeClient.last_request["headers"]
        assert headers["x-rapidapi-key"] == "test-key"
        assert headers["x-rapidapi-host"] == "investing-com-ultimate-api.p.rapidapi.com"
        assert _FakeClient.last_request["url"].startswith("https://investing-com-ultimate-api")

    async def test_fetch_economic_events_parses(self, configured, fake_http):
        _FakeClient.queued = [
            _FakeResponse(
                200,
                {
                    "data": [
                        {
                            "event": "Fed Rate Decision",
                            "importance": "high",
                            "country": "US",
                            "date": "2026-07-16T18:00:00Z",
                        }
                    ]
                },
            )
        ]
        events = await inv.fetch_economic_events()
        assert len(events) == 1
        assert events[0]["event_name"] == "Fed Rate Decision"
        assert events[0]["impact"] == "high"

    async def test_fetch_earnings_parses(self, configured, fake_http):
        _FakeClient.queued = [
            _FakeResponse(
                200,
                {"data": [{"symbol": "AAPL", "company": "Apple Inc", "date": "2026-07-20"}]},
            )
        ]
        earnings = await inv.fetch_earnings()
        assert len(earnings) == 1
        assert earnings[0]["event_type"] == "earnings"
        assert earnings[0]["tickers_affected"] == ["AAPL"]

    async def test_fetch_quote_parses(self, configured, fake_http):
        _FakeClient.queued = [
            _FakeResponse(200, {"data": [{"last": "195.5", "change_percent": "1.2%"}]})
        ]
        quote = await inv.fetch_quote("AAPL")
        assert quote is not None
        assert quote["price"] == 195.5
        assert quote["change_percent"] == 1.2

    async def test_market_intelligence_empty_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(inv.settings, "RAPIDAPI_KEY", "")
        intel = await inv.fetch_market_intelligence(["AAPL"])
        assert intel == {"events": [], "earnings": [], "quotes": {}, "configured": False}

    async def test_get_returns_none_on_500(self, configured, fake_http):
        _FakeClient.queued = [_FakeResponse(500, {})]
        result = await inv._get("/economic-calendar/")
        assert result is None
