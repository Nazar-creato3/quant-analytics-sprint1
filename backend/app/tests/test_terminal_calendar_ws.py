"""Tests for terminal calendar endpoint + WS /ws/terminal smoke."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StarletteTestClient

from app.api.v1.endpoints.terminal import router as terminal_router
from app.api.v1.endpoints.websocket import router as ws_router
from app.services.terminal_platform.models import CalendarEvent, FetchResult


def _calendar_app() -> FastAPI:
    app = FastAPI()
    app.include_router(terminal_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_from_finnhub_excludes_earnings():
    """Terminal economic calendar must not show per-ticker Finnhub earnings rows."""
    from app.services.terminal_platform import calendar as cal

    economic = [
        {
            "event_name": "Initial Jobless Claims",
            "event_date": "2026-09-10T12:30:00+00:00",
            "country": "US",
            "impact": "medium",
            "estimate": "220",
            "source": "finnhub",
        }
    ]
    with patch(
        "app.services.macro.client.fetch_finnhub_calendar",
        new=AsyncMock(return_value=economic),
    ):
        events = await cal._from_finnhub(limit=10)

    assert len(events) == 1
    assert events[0].title == "Initial Jobless Claims"
    assert events[0].provider == "finnhub"
    assert all(" earnings" not in e.title.lower() or "jobless" in e.title.lower() for e in events)


@pytest.mark.asyncio
async def test_fetch_terminal_calendar_prefers_rich_finnhub_over_title_only_fmp():
    from app.services.terminal_platform import calendar as cal
    from app.services.terminal_platform.models import CalendarEvent

    sparse_fmp = [
        CalendarEvent(
            id="fmp-1",
            title="US CPI (YoY)",
            when=datetime(2026, 9, 10, 12, 30, tzinfo=timezone.utc),
            region="US",
            importance="high",
            provider="fmp",
        )
    ]

    class _FakeFmp:
        async def fetch_economic_calendar(self, **kwargs):
            return FetchResult(success=True, data=sparse_fmp, provider="fmp")

    class _FakeRouter:
        def get_provider(self, name: str):
            return _FakeFmp() if name == "fmp" else None

    rich_finnhub = [
        {
            "event_name": "US CPI (YoY)",
            "event_date": "2026-09-10T12:30:00+00:00",
            "country": "US",
            "impact": "high",
            "estimate": "3.0",
            "actual": "3.1",
            "previous": "2.9",
            "source": "finnhub",
        }
    ]

    with (
        patch(
            "app.services.terminal_platform.factory.get_terminal_router",
            return_value=_FakeRouter(),
        ),
        patch(
            "app.services.macro.client.fetch_finnhub_calendar",
            new=AsyncMock(return_value=rich_finnhub),
        ),
        patch.object(cal, "_from_investing", new=AsyncMock(return_value=[])),
    ):
        result = await cal.fetch_terminal_calendar(limit=10)

    assert result.success is True
    assert result.data
    row = result.data[0]
    assert row.actual == "3.1"
    assert row.expected == "3.0"
    assert row.previous == "2.9"


@pytest.mark.asyncio
async def test_fetch_terminal_calendar_falls_back_to_free():
    from app.services.terminal_platform import calendar as cal

    async def _fmp_fail(**kwargs):
        return FetchResult(
            success=False,
            error="403 Forbidden",
            error_code="PROVIDER_ERROR",
            provider="fmp",
        )

    class _FakeFmp:
        async def fetch_economic_calendar(self, **kwargs):
            return await _fmp_fail(**kwargs)

    class _FakeRouter:
        def get_provider(self, name: str):
            return _FakeFmp() if name == "fmp" else None

    with (
        patch(
            "app.services.terminal_platform.factory.get_terminal_router",
            return_value=_FakeRouter(),
        ),
        patch.object(cal, "_from_finnhub", new=AsyncMock(return_value=[])),
        patch.object(cal, "_from_investing", new=AsyncMock(return_value=[])),
    ):
        result = await cal.fetch_terminal_calendar(limit=10)

    assert result.success is True
    assert result.provider == "free_policy_calendar"
    assert result.data
    assert any("FOMC" in e.title or "CBR" in e.title for e in result.data)


def test_calendar_endpoint_success():
    events = [
        CalendarEvent(
            id="e1",
            title="US CPI (YoY)",
            when=datetime(2026, 9, 10, 12, 30, tzinfo=timezone.utc),
            region="US",
            importance="high",
            expected="3.0%",
            provider="investing_rapidapi",
        )
    ]

    async def _fake_fetch(**kwargs):
        return FetchResult(success=True, data=events, provider="investing_rapidapi")

    with patch(
        "app.services.terminal_platform.calendar.fetch_terminal_calendar",
        new=_fake_fetch,
    ):
        client = TestClient(_calendar_app())
        r = client.get("/api/v1/terminal/calendar", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["provider"] == "investing_rapidapi"
    assert body["data"][0]["title"] == "US CPI (YoY)"
    assert body["data"][0]["importance"] == "high"


def test_calendar_endpoint_all_failed():
    async def _fake_fetch(**kwargs):
        return FetchResult(
            success=False,
            error="All calendar sources failed",
            error_code="ALL_FAILED",
            provider="router",
        )

    with (
        patch(
            "app.services.terminal_platform.calendar.fetch_terminal_calendar",
            new=_fake_fetch,
        ),
        patch(
            "app.services.terminal_platform.market.feed_freshness.freshness_from_calendar_cache",
            return_value=(None, None),
        ),
    ):
        client = TestClient(_calendar_app())
        r = client.get("/api/v1/terminal/calendar")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error_code"] == "ALL_FAILED"


def test_ws_terminal_connect_smoke():
    app = FastAPI()
    app.include_router(ws_router, prefix="/api/v1")

    async def _noop_pulse(ws, symbols):  # noqa: ANN001
        return

    with patch(
        "app.api.v1.endpoints.websocket._terminal_pulse_broadcaster",
        new=_noop_pulse,
    ):
        client = StarletteTestClient(app)
        with client.websocket_connect("/api/v1/ws/terminal") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert "symbols" in msg
            ws.send_json({"action": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"


def test_fmp_impact_mapping():
    from app.services.terminal_platform.providers.fmp import FmpDataProvider

    assert FmpDataProvider._impact_to_importance("High") == "high"
    assert FmpDataProvider._impact_to_importance("Medium") == "medium"
    assert FmpDataProvider._impact_to_importance("Low") == "low"
    assert FmpDataProvider._impact_to_importance(None) is None
