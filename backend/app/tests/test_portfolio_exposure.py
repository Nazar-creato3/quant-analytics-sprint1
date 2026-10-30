"""Tests for portfolio exposure calculation and balance refresh."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import Maneuver, ManeuverStatus
from app.services.portfolio import exposure as exposure_mod
from app.services.risk.position_limits import evaluate_position_limits


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class _FakeSession:
    def __init__(self, maneuvers):
        self._maneuvers = maneuvers

    async def execute(self, _stmt):
        return _FakeResult(self._maneuvers)


def _maneuver(**kw) -> Maneuver:
    defaults = dict(
        id="m-1",
        ticker="AAPL",
        direction="long",
        position_size_usd=5_000.0,
        status=ManeuverStatus.FILLED,
        risk_percent=1.0,
        confidence=0.6,
        time_horizon="1-3 days",
    )
    defaults.update(kw)
    return Maneuver(**defaults)


def _flat_grid_bot(*, bot_id: str = "bot-1", total_capital: float = 10_000.0) -> dict:
    return {
        "bot_id": bot_id,
        "is_active": True,
        "config": {
            "ticker": "AAPL",
            "total_capital": total_capital,
            "lower_price": 170.0,
            "upper_price": 190.0,
            "grid_count": 5,
        },
        "levels": [],
        "summary": {"last_price": 180.0},
    }


def _grid_bot_with_open_position(*, total_capital: float = 10_000.0) -> dict:
    return {
        "bot_id": "bot-2",
        "is_active": True,
        "config": {
            "ticker": "AAPL",
            "total_capital": total_capital,
            "lower_price": 170.0,
            "upper_price": 190.0,
            "grid_count": 5,
        },
        "levels": [
            {
                "side": "buy",
                "status": "filled",
                "price": 180.0,
                "fill_price": 180.0,
                "quantity": 10.0,
            }
        ],
        "summary": {"last_price": 182.0},
    }


class TestGridExposure:
    async def test_flat_active_grid_does_not_count_total_capital(self, monkeypatch):
        monkeypatch.setattr(
            exposure_mod,
            "cache_get",
            AsyncMock(return_value={"bot-1": _flat_grid_bot()}),
        )

        grid_usd, bots_with_positions, active_bots = await exposure_mod.grid_exposure()

        assert grid_usd == 0.0
        assert bots_with_positions == 0
        assert active_bots == 1

    async def test_grid_counts_actual_open_notional(self, monkeypatch):
        monkeypatch.setattr(
            exposure_mod,
            "cache_get",
            AsyncMock(return_value={"bot-2": _grid_bot_with_open_position()}),
        )

        grid_usd, bots_with_positions, _active = await exposure_mod.grid_exposure()

        assert grid_usd == pytest.approx(1820.0)
        assert bots_with_positions == 1


class TestCurrentExposure:
    async def test_zero_positions_zero_exposure(self, monkeypatch):
        monkeypatch.setattr(
            exposure_mod,
            "cache_get",
            AsyncMock(return_value={"bot-1": _flat_grid_bot()}),
        )
        session = _FakeSession([])

        snapshot = await exposure_mod.current_exposure(session)

        assert snapshot.total_usd == 0.0
        assert snapshot.open_maneuvers == 0
        assert snapshot.grid_usd == 0.0

    async def test_unscoped_maneuver_exposure_is_empty(self):
        """Without an owner, do not scan every user's open book."""
        session = _FakeSession([_maneuver(position_size_usd=9_999.0)])
        usd, count = await exposure_mod.maneuver_exposure(session)
        assert usd == 0.0
        assert count == 0


class TestReconcileStaleGrid:
    async def test_deactivates_flat_active_grid(self, monkeypatch):
        bots = {"bot-1": _flat_grid_bot()}
        cache_set = AsyncMock(return_value=True)
        monkeypatch.setattr(exposure_mod, "cache_get", AsyncMock(return_value=bots))
        monkeypatch.setattr(exposure_mod, "cache_set", cache_set)

        result = await exposure_mod.reconcile_stale_grid_exposure()

        assert result["deactivated_grid_bots"] == 1
        assert result["released_capital_usd"] == 10_000.0
        cache_set.assert_awaited_once()
        saved = cache_set.await_args.args[1]
        assert saved["bot-1"]["is_active"] is False


class TestPositionLimitsWithFlatBook:
    async def test_zero_exposure_allows_new_trade(self, monkeypatch):
        monkeypatch.setattr(
            exposure_mod,
            "cache_get",
            AsyncMock(return_value={"bot-1": _flat_grid_bot()}),
        )

        async def fake_portfolio_size(_email: str) -> float:
            return 10_000.0

        monkeypatch.setattr(
            "app.services.risk.position_limits._portfolio_size",
            fake_portfolio_size,
        )
        monkeypatch.setattr(
            "app.services.portfolio.user_scope.get_user_by_email",
            AsyncMock(return_value=None),
        )

        session = _FakeSession([])
        maneuver = _maneuver(position_size_usd=1_000.0)

        decision = await evaluate_position_limits(session, maneuver, "ops@test.com")

        assert decision.allowed is True
        assert decision.approved_size_usd == 1_000.0
