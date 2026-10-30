"""Tests for golden-research grid bot modules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.grid.auto_calibrate import calculate_auto_grid
from app.services.grid.backtest import run_grid_backtest
from app.services.grid.circuit_breaker import PumpDumpCircuitBreaker
from app.services.grid.config import GridConfigModel, GridType
from app.services.grid.executor import GridExecutor
from app.services.grid.levels import compute_grid_prices
from app.services.grid.triple_barrier import BarrierExit, TripleBarrierConfig, TripleBarrierPosition


class TestGridLevels:
    def test_arithmetic_spacing(self):
        prices = compute_grid_prices(100.0, 200.0, 10, GridType.ARITHMETIC)
        assert len(prices) == 11
        assert prices[0] == 100.0
        assert prices[-1] == 200.0
        assert abs(prices[1] - prices[0] - 10.0) < 1e-6

    def test_geometric_spacing(self):
        prices = compute_grid_prices(100.0, 200.0, 10, GridType.GEOMETRIC)
        assert len(prices) == 11
        ratios = [prices[i + 1] / prices[i] for i in range(len(prices) - 1)]
        assert all(abs(r - ratios[0]) < 1e-4 for r in ratios)


class TestAutoCalibrate:
    def test_calculate_auto_grid_bounds(self):
        closes = [100 + i * 0.5 for i in range(30)]
        result = calculate_auto_grid("AAPL", 10_000, 115.0, closes, risk_level="medium")
        cfg = result.config
        assert cfg.lower_bound < 115.0 < cfg.upper_bound
        assert cfg.num_levels >= 4
        assert result.realized_volatility >= 0


class TestTripleBarrier:
    def test_take_profit_triggers_first(self):
        now = datetime.now(timezone.utc)
        pos = TripleBarrierPosition(
            level_id="t1",
            side="buy",
            entry_price=100.0,
            quantity=1.0,
            opened_at=now,
            config=TripleBarrierConfig(take_profit_pct=0.02, stop_loss_pct=0.05, max_hold_hours=72),
        )
        assert pos.check_barriers(102.5, now) == BarrierExit.TAKE_PROFIT

    def test_time_barrier(self):
        now = datetime.now(timezone.utc)
        pos = TripleBarrierPosition(
            level_id="t2",
            side="buy",
            entry_price=100.0,
            quantity=1.0,
            opened_at=now - timedelta(hours=100),
            config=TripleBarrierConfig(max_hold_hours=72),
        )
        assert pos.check_barriers(100.5, now) == BarrierExit.TIME

    def test_close_computes_pnl(self):
        now = datetime.now(timezone.utc)
        pos = TripleBarrierPosition(
            level_id="t3", side="buy", entry_price=100.0, quantity=2.0, opened_at=now,
        )
        pnl = pos.close(105.0, BarrierExit.TAKE_PROFIT, now)
        assert pnl == pytest.approx(10.0)
        assert pos.is_closed


class TestCircuitBreaker:
    def test_pump_triggers_pause(self):
        cb = PumpDumpCircuitBreaker(threshold_pct=3.0, window_seconds=600)
        t0 = datetime.now(timezone.utc)
        cb.on_price(100.0, t0)
        ev = cb.on_price(104.0, t0 + timedelta(seconds=60))
        assert ev is not None
        assert ev.event == "pause"
        assert not cb.allows_new_orders()


class TestGridExecutor:
    def test_initialize_levels(self):
        cfg = GridConfigModel(
            symbol="BTCUSDT",
            upper_bound=110.0,
            lower_bound=90.0,
            num_levels=10,
            capital_allocated=5000.0,
            grid_type=GridType.GEOMETRIC,
        )
        ex = GridExecutor(cfg)
        levels = ex.initialize(100.0)
        assert len(levels) >= 2
        assert any(l.side == "buy" for l in levels)
        assert any(l.side == "sell" for l in levels)

    def test_dca_mode_on_breakout(self):
        cfg = GridConfigModel(
            symbol="ETHUSDT",
            upper_bound=105.0,
            lower_bound=95.0,
            num_levels=5,
            capital_allocated=1000.0,
            dca_enabled=True,
        )
        ex = GridExecutor(cfg)
        ex.initialize(100.0)
        result = ex.on_price_tick(106.0, 100.0)
        assert result.new_state.value == "dca_mode"


class TestGridBacktest:
    def test_backtest_with_fees(self):
        prices = [100 + (i % 5 - 2) * 0.5 for i in range(60)]
        cfg = GridConfigModel(
            symbol="TEST",
            upper_bound=105.0,
            lower_bound=95.0,
            num_levels=8,
            capital_allocated=10_000.0,
            fee_bps=10.0,
            slippage_bps=5.0,
        )
        result = run_grid_backtest(prices, cfg)
        assert result.n_trades >= 0
        assert len(result.equity_curve) == len(prices)
        assert result.total_fees >= 0

    def test_liquidation_with_leverage(self):
        prices = [100.0 - i * 2.0 for i in range(30)]
        cfg = GridConfigModel(
            symbol="TEST",
            upper_bound=110.0,
            lower_bound=80.0,
            num_levels=5,
            capital_allocated=10_000.0,
            leverage=10.0,
        )
        result = run_grid_backtest(prices, cfg, maintenance_margin=0.05)
        assert result.liquidation_events >= 0
