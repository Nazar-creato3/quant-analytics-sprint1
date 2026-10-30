"""Regression: NavBar metrics include live unrealized P&L (Prompt 94)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Maneuver, ManeuverStatus
from app.services.portfolio import exposure as exposure_mod
from app.schemas.portfolio import PortfolioMetricsOut
from app.services.portfolio.metrics import (
    _attach_allocation_and_account,
    _internal_metrics,
    _user_paper_equity,
)
from app.services.portfolio.position_analytics import unrealized_net_pnl


def _filled_long(**kw) -> Maneuver:
    defaults = dict(
        id="m-live-1",
        ticker="AAPL",
        direction="long",
        position_size_usd=1_000.0,
        fill_price=100.0,
        status=ManeuverStatus.FILLED,
        risk_percent=1.0,
        confidence=0.7,
        time_horizon="1-3 days",
    )
    defaults.update(kw)
    return Maneuver(**defaults)


class TestLivePortfolioMetrics:
    async def test_synthetic_price_changes_total_usd(self, monkeypatch):
        """Header SUM must move when mark price moves — same formula as positions tab."""
        maneuver = _filled_long()
        at_100 = unrealized_net_pnl(maneuver, 100.0)
        at_110 = unrealized_net_pnl(maneuver, 110.0)
        assert at_100 is not None and at_110 is not None
        assert at_110 > at_100

        snapshot = exposure_mod.ExposureSnapshot(
            maneuver_usd=1_000.0,
            grid_usd=0.0,
            open_maneuvers=1,
            grid_bots_with_positions=0,
            active_grid_bots=0,
        )

        async def fake_paper_equity(_email: str, _db=None) -> float:
            return 10_000.0

        async def fake_portfolio_size(_email: str) -> float:
            return 10_000.0

        async def fake_confidence(_email: str) -> float:
            return 0.5

        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_paper_equity",
            fake_paper_equity,
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_portfolio_size",
            fake_portfolio_size,
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_confidence_threshold",
            fake_confidence,
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics.current_exposure",
            AsyncMock(return_value=snapshot),
        )
        monkeypatch.setattr(
            "app.services.portfolio.user_scope.get_user_by_email",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "app.services.portfolio.live_equity._open_maneuvers",
            AsyncMock(return_value=[maneuver]),
        )
        monkeypatch.setattr(
            "app.services.portfolio.live_equity._realized_closed_pnl",
            AsyncMock(return_value=0.0),
        )
        monkeypatch.setattr(
            "app.services.portfolio.live_equity.latest_prices",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            "app.services.portfolio.live_equity.cache_get",
            AsyncMock(return_value={}),
        )

        db = AsyncMock()
        baseline = await _internal_metrics("ops@test.com", db, price_overrides={"AAPL": 100.0})
        bumped = await _internal_metrics("ops@test.com", db, price_overrides={"AAPL": 110.0})

        assert baseline.unrealized_pnl_usd == pytest.approx(at_100)
        assert bumped.unrealized_pnl_usd == pytest.approx(at_110)
        assert bumped.total_usd - baseline.total_usd == pytest.approx(at_110 - at_100)
        assert bumped.trading_usd == pytest.approx(1_000.0 + at_110)
        assert baseline.trading_usd == pytest.approx(1_000.0 + at_100)
        assert baseline.total_usd == pytest.approx(10_000.0 + at_100)
        assert bumped.total_usd == pytest.approx(10_000.0 + at_110)
        assert baseline.balance_usd + baseline.trading_usd == pytest.approx(baseline.total_usd)
        assert bumped.balance_usd + bumped.trading_usd == pytest.approx(bumped.total_usd)

    async def test_realized_closed_included_in_balance(self, monkeypatch):
        snapshot = exposure_mod.ExposureSnapshot(
            maneuver_usd=0.0,
            grid_usd=0.0,
            open_maneuvers=0,
            grid_bots_with_positions=0,
            active_grid_bots=0,
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_paper_equity",
            AsyncMock(return_value=10_000.0),
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_portfolio_size",
            AsyncMock(return_value=10_000.0),
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics.current_exposure",
            AsyncMock(return_value=snapshot),
        )
        monkeypatch.setattr(
            "app.services.portfolio.user_scope.get_user_by_email",
            AsyncMock(return_value=None),
        )

        with patch(
            "app.services.portfolio.metrics.compute_live_pnl",
            AsyncMock(
                return_value=type(
                    "Snap",
                    (),
                    {
                        "unrealized_total_usd": 0.0,
                        "realized_closed_usd": 250.0,
                        "unrealized_maneuver_usd": 0.0,
                        "unrealized_grid_usd": 0.0,
                        "deployed_notional_usd": 0.0,
                        "live_pnl_usd": 250.0,
                    },
                )()
            ),
        ):
            metrics = await _internal_metrics("ops@test.com", AsyncMock())

        assert metrics.realized_pnl_usd == 250.0
        assert metrics.total_usd == pytest.approx(10_250.0)
        assert metrics.balance_usd == pytest.approx(10_250.0)
        assert metrics.trading_usd == 0.0


class TestCapIsNotBalance:
    async def test_missing_paper_equity_is_not_the_cap(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_settings_merged",
            AsyncMock(return_value={"portfolio_size": 600.0}),
        )
        equity = await _user_paper_equity("ops@test.com")
        assert equity == 0.0

    async def test_raising_cap_does_not_increase_ledger_total(self, monkeypatch):
        snapshot = exposure_mod.ExposureSnapshot(
            maneuver_usd=31.0,
            grid_usd=0.0,
            open_maneuvers=1,
            grid_bots_with_positions=0,
            active_grid_bots=0,
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_paper_equity",
            AsyncMock(return_value=763.0),
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics.current_exposure",
            AsyncMock(return_value=snapshot),
        )
        monkeypatch.setattr(
            "app.services.portfolio.user_scope.get_user_by_email",
            AsyncMock(return_value=None),
        )
        pnl = type(
            "Snap",
            (),
            {
                "unrealized_total_usd": 0.0,
                "realized_closed_usd": -1.0,
                "unrealized_maneuver_usd": 0.0,
                "unrealized_grid_usd": 0.0,
                "deployed_notional_usd": 31.0,
                "live_pnl_usd": -1.0,
            },
        )()
        monkeypatch.setattr(
            "app.services.portfolio.metrics.compute_live_pnl",
            AsyncMock(return_value=pnl),
        )

        async def cap_100(_email: str) -> float:
            return 100.0

        async def cap_600(_email: str) -> float:
            return 600.0

        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_portfolio_size",
            cap_100,
        )
        at_100 = await _internal_metrics("ops@test.com", AsyncMock())
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_portfolio_size",
            cap_600,
        )
        at_600 = await _internal_metrics("ops@test.com", AsyncMock())

        assert at_100.total_usd == pytest.approx(at_600.total_usd)
        assert at_100.total_usd == pytest.approx(762.0)
        assert at_100.trading_usd == pytest.approx(31.0)

    async def test_paper_does_not_overlay_venue_totals_on_ledger(self, monkeypatch):
        metrics = PortfolioMetricsOut(
            trading_usd=31.0,
            balance_usd=600.0,
            total_usd=631.0,
            mode="paper",
            source="internal",
            as_of="2026-09-11T00:00:00+00:00",
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._venue_account_totals",
            AsyncMock(return_value=(731.0, 762.0)),
        )
        out = await _attach_allocation_and_account(
            metrics,
            portfolio_allocation_usd=600.0,
            account_mode="paper",
        )
        assert out.portfolio_allocation_usd == 600.0
        assert out.total_usd == 631.0
        assert out.trading_usd == 31.0
        assert out.mode == "paper"

    async def test_live_uses_user_venue_total_not_cap(self, monkeypatch):
        metrics = PortfolioMetricsOut(
            trading_usd=31.0,
            balance_usd=600.0,
            total_usd=631.0,
            mode="paper",
            source="internal",
            as_of="2026-09-11T00:00:00+00:00",
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._venue_account_totals",
            AsyncMock(return_value=(731.0, 762.0)),
        )
        out = await _attach_allocation_and_account(
            metrics,
            portfolio_allocation_usd=600.0,
            account_mode="live",
            user_id="u1",
        )
        assert out.total_usd == 762.0
        assert out.portfolio_allocation_usd == 600.0
        assert out.total_usd != pytest.approx(762.0 + 600.0)

    async def test_live_clamps_cap_to_venue_total(self, monkeypatch):
        metrics = PortfolioMetricsOut(
            trading_usd=31.0,
            balance_usd=600.0,
            total_usd=631.0,
            mode="paper",
            source="internal",
            as_of="2026-09-11T00:00:00+00:00",
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._venue_account_totals",
            AsyncMock(return_value=(731.0, 762.0)),
        )
        out = await _attach_allocation_and_account(
            metrics,
            portfolio_allocation_usd=50_000.0,
            account_mode="live",
            user_id="u1",
        )
        assert out.total_usd == 762.0
        assert out.portfolio_allocation_usd == 762.0
        assert out.mode == "live"

    async def test_live_empty_wallet_keeps_paper_ledger(self, monkeypatch):
        metrics = PortfolioMetricsOut(
            trading_usd=31.0,
            balance_usd=269.31,
            total_usd=300.31,
            mode="paper",
            source="internal",
            as_of="2026-09-11T00:00:00+00:00",
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._venue_account_totals",
            AsyncMock(return_value=(0.0, 0.0)),
        )
        out = await _attach_allocation_and_account(
            metrics,
            portfolio_allocation_usd=300.31,
            account_mode="live",
            user_id="u1",
        )
        assert out.mode == "paper"
        assert out.total_usd == 300.31
        assert out.trading_usd == 31.0
        assert out.balance_usd == 269.31
        assert out.portfolio_allocation_usd == 300.31


def _metrics(**kw) -> PortfolioMetricsOut:
    defaults = dict(
        trading_usd=331.0,
        balance_usd=10_000.0,
        total_usd=10_331.0,
        mode="paper",
        source="internal",
        open_maneuvers=1,
        as_of="2026-09-11T00:00:00+00:00",
    )
    defaults.update(kw)
    return PortfolioMetricsOut(**defaults)


class TestHoldbackTransientFlatBook:
    async def test_first_empty_tick_keeps_last_good(self, monkeypatch):
        from app.services.portfolio.metrics import _holdback_transient_flat_book

        good = _metrics()
        empty = _metrics(
            trading_usd=0.0,
            balance_usd=10_000.0,
            total_usd=10_000.0,
            open_maneuvers=0,
            as_of="2026-09-11T00:00:15+00:00",
        )
        store: dict = {}

        async def fake_get(key: str):
            return store.get(key)

        async def fake_set(key: str, value, ttl=None):
            store[key] = value
            return True

        monkeypatch.setattr("app.services.portfolio.metrics.cache_get", fake_get)
        monkeypatch.setattr("app.services.portfolio.metrics.cache_set", fake_set)

        kept = await _holdback_transient_flat_book("ops@test.com", good)
        assert kept.total_usd == 10_331.0
        held = await _holdback_transient_flat_book("ops@test.com", empty)
        assert held.trading_usd == 331.0
        assert held.total_usd == 10_331.0
        assert held.as_of == empty.as_of

    async def test_second_empty_tick_accepts_flat_book(self, monkeypatch):
        from app.services.portfolio.metrics import _holdback_transient_flat_book

        good = _metrics()
        empty = _metrics(
            trading_usd=0.0,
            balance_usd=10_000.0,
            total_usd=10_000.0,
            open_maneuvers=0,
            as_of="2026-09-11T00:00:30+00:00",
        )
        store: dict = {}

        async def fake_get(key: str):
            return store.get(key)

        async def fake_set(key: str, value, ttl=None):
            store[key] = value
            return True

        monkeypatch.setattr("app.services.portfolio.metrics.cache_get", fake_get)
        monkeypatch.setattr("app.services.portfolio.metrics.cache_set", fake_set)

        await _holdback_transient_flat_book("ops@test.com", good)
        await _holdback_transient_flat_book("ops@test.com", empty)
        accepted = await _holdback_transient_flat_book("ops@test.com", empty)
        assert accepted.trading_usd == 0.0
        assert accepted.total_usd == 10_000.0

