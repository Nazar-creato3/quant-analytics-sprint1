"""Tests for single-maneuver cancel vs bulk flatten."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models import AuditLog, Maneuver, ManeuverStatus
from app.domain.deal_intent_enums import DealIntentStatus
from app.domain.deal_intent_fsm import DealIntentEvent
from app.domain.deal_intent import transition_deal_intent_status
from app.services.portfolio import cancel_maneuver as cancel_mod
from app.services.portfolio import flatten as flatten_mod
from app.utils.audit import AuditAction


class _FakeResult:
    def __init__(self, items):
        self._items = items if isinstance(items, list) else [items]

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar_one_or_none(self):
        if not self._items:
            return None
        return self._items[0]


class _FakeSession:
    def __init__(self, maneuvers=None):
        self._maneuvers = {m.id: m for m in (maneuvers or [])}
        self.added: list = []
        self.committed = False

    async def execute(self, _stmt):
        if len(self._maneuvers) == 1:
            return _FakeResult(next(iter(self._maneuvers.values())))
        return _FakeResult(list(self._maneuvers.values()))

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
        status=ManeuverStatus.APPROVED,
        risk_percent=1.0,
        confidence=0.6,
        time_horizon="1-3 days",
        report_id="r-1",
        rank=1,
        strategy_type="momentum",
    )
    defaults.update(kw)
    return Maneuver(**defaults)


class TestCancelManeuverService:
    async def test_cancels_approved_maneuver_only(self):
        approved = _maneuver(id="a", status=ManeuverStatus.APPROVED)
        session = _FakeSession([approved])

        result = await cancel_mod.cancel_maneuver(session, "a", email=None)

        assert result.action == "cancelled"
        assert approved.status == ManeuverStatus.CANCELLED
        assert result.status_before == "approved"
        assert result.status_after == "cancelled"
        audit = next(o for o in session.added if isinstance(o, AuditLog))
        assert audit.action == AuditAction.MANEUVER_CANCELLED
        assert audit.resource_id == "a"
        assert audit.details["action"] == "cancelled"
        assert session.committed is True

    async def test_cancels_pending_maneuver(self):
        pending = _maneuver(id="p", status=ManeuverStatus.PENDING)
        session = _FakeSession([pending])

        result = await cancel_mod.cancel_maneuver(session, "p", email=None)

        assert result.action == "cancelled"
        assert pending.status == ManeuverStatus.CANCELLED

    async def test_closes_filled_paper_position(self, monkeypatch):
        async def fake_prices(_db, _tickers):
            return {"MSFT": 110.0}

        monkeypatch.setattr(cancel_mod, "latest_prices", fake_prices)
        filled = _maneuver(id="f", status=ManeuverStatus.FILLED)
        session = _FakeSession([filled])

        result = await cancel_mod.cancel_maneuver(session, "f", email=None)

        assert result.action == "closed"
        assert filled.status == ManeuverStatus.CLOSED
        assert filled.realized_pnl is not None

    async def test_rejects_terminal_status(self):
        rejected = _maneuver(id="r", status=ManeuverStatus.REJECTED)
        session = _FakeSession([rejected])

        with pytest.raises(cancel_mod.ManeuverNotCancellable):
            await cancel_mod.cancel_maneuver(session, "r", email=None)

    async def test_single_cancel_leaves_sibling_open(self, monkeypatch):
        async def fake_prices(_db, _tickers):
            return {"MSFT": 110.0, "AAPL": 150.0}

        monkeypatch.setattr(flatten_mod, "latest_prices", fake_prices)

        m1 = _maneuver(id="keep", ticker="AAPL", status=ManeuverStatus.FILLED)
        m2 = _maneuver(id="drop", ticker="MSFT", status=ManeuverStatus.APPROVED)

        cancel_session = _FakeSession([m2])
        await cancel_mod.cancel_maneuver(cancel_session, "drop", email=None)
        assert m2.status == ManeuverStatus.CANCELLED
        assert m1.status == ManeuverStatus.FILLED

        flatten_session = _FakeSession([m1])
        bulk = await flatten_mod.close_all_positions(flatten_session, email=None)
        assert bulk.closed_count == 1
        assert m1.status == ManeuverStatus.CLOSED


class TestCancelManeuverEndpoint:
    def test_requires_auth(self):
        from app.api.v1.endpoints.maneuvers import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/maneuvers/m-1/cancel")
        assert resp.status_code in (401, 403, 422)


class TestDealIntentCancelFsm:
    def test_cancel_from_approved(self):
        next_status = transition_deal_intent_status(
            DealIntentStatus.APPROVED,
            DealIntentEvent.CANCEL,
        )
        assert next_status == DealIntentStatus.CANCELLED

    def test_cancel_from_pending_approval(self):
        next_status = transition_deal_intent_status(
            DealIntentStatus.PENDING_APPROVAL,
            DealIntentEvent.CANCEL,
        )
        assert next_status == DealIntentStatus.CANCELLED
