"""WS positions snapshot builder smoke tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.endpoints import websocket as ws_module
from app.services.portfolio.positions_snapshot import build_open_positions_snapshot


@pytest.mark.asyncio
async def test_build_open_positions_snapshot_empty_user():
    db = AsyncMock()
    with patch(
        "app.services.portfolio.positions_snapshot.get_user_by_email",
        new=AsyncMock(return_value=None),
    ):
        snap = await build_open_positions_snapshot("nobody@example.com", db)
    assert snap["items"] == []
    assert snap["live_snapshot"]["stale"] is True


@pytest.mark.asyncio
async def test_build_open_positions_snapshot_enriches_rows():
    from types import SimpleNamespace

    from app.schemas.schemas import ManeuverStatus, StrategyType

    db = AsyncMock()
    user = SimpleNamespace(id="u1")
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    maneuver = SimpleNamespace(
        id="m1",
        rank=1,
        ticker="AAPL",
        strategy_type=StrategyType.TREND_FOLLOWING,
        direction="long",
        entry_zone_low=100.0,
        entry_zone_high=105.0,
        exit_zone_low=110.0,
        exit_zone_high=115.0,
        stop_loss=95.0,
        take_profit=115.0,
        invalidation_level=95.0,
        risk_percent=1.0,
        position_size_usd=1000.0,
        confidence=0.6,
        time_horizon="3-5 дней",
        status=ManeuverStatus.FILLED,
        trading_mode="paper",
        fill_price=102.0,
        filled_at=now,
        created_at=now,
        signal_meta=None,
    )

    class _Scalars:
        def all(self):
            return [maneuver]

    class _Result:
        def scalars(self):
            return _Scalars()

    db.execute = AsyncMock(return_value=_Result())

    enrich = {
        "m1": {
            "current_price": 103.5,
            "unrealized_pnl": 14.7,
            "time_to_close": 86400,
            "horizon_end_at": "2026-08-10T12:00:00+00:00",
            "horizon_expired": False,
        }
    }

    with patch(
        "app.services.portfolio.positions_snapshot.get_user_by_email",
        new=AsyncMock(return_value=user),
    ), patch(
        "app.core.rbac_deps.get_user_and_role",
        new=AsyncMock(return_value=(user, "operator")),
    ), patch(
        "app.domain.rbac.is_staff_admin_role",
        return_value=False,
    ), patch(
        "app.services.portfolio.positions_snapshot.enrich_maneuvers",
        new=AsyncMock(return_value=enrich),
    ):
        snap = await build_open_positions_snapshot("op@example.com", db)

    assert snap["total"] == 1
    assert snap["items"][0]["current_price"] == 103.5
    assert snap["items"][0]["horizon_end_at"] == "2026-08-10T12:00:00+00:00"
    assert snap["items"][0]["expiry_at"] == "2026-08-10T12:00:00+00:00"
    assert snap["live_snapshot"]["stale"] is False


@pytest.mark.asyncio
async def test_positions_broadcaster_sets_rls_user_id():
    """WS positions path must bind app.user_id like REST get_user_db."""
    from types import SimpleNamespace

    ws = AsyncMock()
    user = SimpleNamespace(id="user-a")
    snapshot = {"items": [], "total": 0, "live_snapshot": {"stale": False}}

    mock_db = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.db.session.AsyncSessionLocal", return_value=mock_cm), patch(
        "app.services.portfolio.user_scope.get_user_by_email",
        new=AsyncMock(return_value=user),
    ), patch(
        "app.db.rls.set_session_user_id",
        new=AsyncMock(),
    ) as mock_set_rls, patch(
        "asyncio.wait_for",
        new=AsyncMock(return_value=snapshot),
    ), patch(
        "asyncio.sleep",
        new=AsyncMock(side_effect=RuntimeError("stop after one tick")),
    ):
        with pytest.raises(RuntimeError, match="stop after one tick"):
            await ws_module._positions_broadcaster(ws, "alice@test.com")

    assert mock_set_rls.await_count >= 1
    mock_set_rls.assert_any_await(mock_db, "user-a")
