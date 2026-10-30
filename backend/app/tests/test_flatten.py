"""Tests for the paper-book flatten / close-all service and endpoint."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models import Maneuver, ManeuverStatus
from app.schemas.ops import CloseAllPositionsOut
from app.services.portfolio import flatten as flatten_mod


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class _FakeSession:
    """Minimal AsyncSession stub: only the maneuver select is exercised."""

    def __init__(self, maneuvers):
        self._maneuvers = maneuvers
        self.added: list = []
        self.committed = False

    async def execute(self, _stmt):
        return _FakeResult(self._maneuvers)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


def _maneuver(**kw) -> Maneuver:
    defaults = dict(
        id=kw.pop("id", "m-1"),
        ticker="MSFT",
        direction="long",
        position_size_usd=10_000.0,
        fill_price=100.0,
        status=ManeuverStatus.FILLED,
        risk_percent=1.0,
        confidence=0.6,
        time_horizon="1-3 days",
    )
    defaults.update(kw)
    return Maneuver(**defaults)


class TestCloseAllService:
    async def test_closes_filled_and_cancels_approved(self, monkeypatch):
        async def fake_prices(_db, _tickers):
            return {"MSFT": 110.0, "BTC-USD": 50_000.0}

        monkeypatch.setattr(flatten_mod, "latest_prices", fake_prices)

        filled = _maneuver(id="a", ticker="MSFT", status=ManeuverStatus.FILLED)
        approved = _maneuver(id="b", ticker="BTC-USD", status=ManeuverStatus.APPROVED)
        session = _FakeSession([filled, approved])

        result = await flatten_mod.close_all_positions(session, email=None)

        assert result.closed_count == 1
        assert result.cancelled_count == 1
        assert filled.status == ManeuverStatus.CLOSED
        assert approved.status == ManeuverStatus.CANCELLED
        # Long 10k @100 -> qty 100; +$10/share = +$1000 gross, minus round-trip fees.
        assert filled.realized_pnl is not None and filled.realized_pnl > 0
        assert result.freed_exposure_usd == 10_000.0
        assert session.committed is True

    async def test_no_open_positions(self, monkeypatch):
        async def fake_prices(_db, _tickers):
            return {}

        monkeypatch.setattr(flatten_mod, "latest_prices", fake_prices)
        session = _FakeSession([])
        result = await flatten_mod.close_all_positions(session, email=None)
        assert result.closed_count == 0
        assert result.cancelled_count == 0
        assert "Нет открытых" in result.message

    async def test_refuses_when_live_unlocked(self, monkeypatch):
        # live_trading_unlocked is a computed property (no setter); drive it via
        # the underlying flags instead.
        monkeypatch.setattr(flatten_mod.settings, "LIVE_TRADING_ENABLED", True, raising=False)
        monkeypatch.setattr(
            flatten_mod.settings,
            "LIVE_TRADING_CONFIRMATION",
            "I_UNDERSTAND_THE_RISKS",
            raising=False,
        )
        assert flatten_mod.settings.live_trading_unlocked is True
        session = _FakeSession([_maneuver()])
        with pytest.raises(flatten_mod.LiveFlattenNotSupported):
            await flatten_mod.close_all_positions(session, email=None)


class TestCloseAllSchema:
    def test_schema_defaults(self):
        payload = CloseAllPositionsOut(mode="paper")
        data = payload.model_dump()
        assert data["closed_count"] == 0
        assert data["positions"] == []


class TestCloseAllEndpoint:
    def test_requires_auth(self):
        from app.api.v1.endpoints.ops import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/api/v1/ops/close-all-positions")
        assert resp.status_code in (401, 403, 422)
