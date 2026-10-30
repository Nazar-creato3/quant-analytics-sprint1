"""Tests for Prompt 19 Factor Engine."""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from app.services.factor import (
    FactorEngine,
    FactorEngineConfig,
    FactorName,
    ols_multivariate,
    rolling_factor_regression,
)
from app.services.factor.factor_returns import (
    align_macro_to_timestamps,
    build_factor_return_matrix,
    market_return_series,
    momentum_factor,
    pct_change_series,
)


class TestPctChangeSeries:
    def test_first_observation_zero(self):
        assert pct_change_series([100.0, 110.0]) == pytest.approx([0.0, math.log(1.1)])

    def test_empty(self):
        assert pct_change_series([]) == []


class TestOlsMultivariate:
    def test_recovers_known_weights(self):
        market = [0.01, -0.005, 0.008, 0.002, -0.003, 0.006]
        sector = [0.004, 0.002, -0.001, 0.003, 0.001, -0.002]
        noise = [0.0] * len(market)
        y = [0.5 * m + 0.3 * s + n for m, s, n in zip(market, sector, noise)]
        factor_matrix = [[m, s] for m, s in zip(market, sector)]
        betas, r_squared = ols_multivariate(
            y,
            factor_matrix,
            factor_names=[FactorName.MARKET_BETA, FactorName.SECTOR_FACTOR],
        )
        assert betas[FactorName.MARKET_BETA] == pytest.approx(0.5, abs=1e-6)
        assert betas[FactorName.SECTOR_FACTOR] == pytest.approx(0.3, abs=1e-6)
        assert r_squared == pytest.approx(1.0, abs=1e-6)


class TestRollingFactorRegression:
    def test_produces_results_after_window(self):
        random.seed(7)
        n = 80
        market = [random.gauss(0.0, 0.01) for _ in range(n)]
        sector = [random.gauss(0.0, 0.008) for _ in range(n)]
        noise = [random.gauss(0.0, 0.001) for _ in range(n)]
        y = [0.5 * m + 0.3 * s + e for m, s, e in zip(market, sector, noise)]
        results = rolling_factor_regression(
            y,
            {
                FactorName.MARKET_BETA: market,
                FactorName.SECTOR_FACTOR: sector,
            },
            window=40,
        )
        assert len(results) == n - 40 + 1
        last = results[-1]
        assert last.betas[FactorName.MARKET_BETA] == pytest.approx(0.5, abs=0.12)
        assert last.betas[FactorName.SECTOR_FACTOR] == pytest.approx(0.3, abs=0.12)
        assert last.r_squared > 0.9


class TestFactorReturnBuilders:
    def test_market_return_series(self):
        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t1 = datetime(2025, 1, 2, tzinfo=timezone.utc)
        series = {
            1: [(t0, 0.01), (t1, 0.02)],
            2: [(t0, 0.03), (t1, 0.04)],
        }
        assert market_return_series(series) == pytest.approx([0.02, 0.03])

    def test_momentum_factor(self):
        market = [0.01, 0.02, -0.01, 0.005, 0.003, 0.002]
        result = momentum_factor(market, lookback=3)
        assert result[0:3] == [0.0, 0.0, 0.0]
        assert result[3] == pytest.approx(sum(market[0:3]))
        assert result[5] == pytest.approx(sum(market[2:5]))

    def test_align_macro_forward_fill(self):
        timestamps = [
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 2, tzinfo=timezone.utc),
            datetime(2025, 1, 3, tzinfo=timezone.utc),
        ]
        macro = [
            (datetime(2025, 1, 1, tzinfo=timezone.utc), 100.0),
            (datetime(2025, 1, 3, tzinfo=timezone.utc), 110.0),
        ]
        changes = align_macro_to_timestamps(timestamps, macro)
        assert changes[0] == 0.0
        assert changes[1] == 0.0
        assert changes[2] == pytest.approx(math.log(1.1))

    def test_build_factor_return_matrix(self):
        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t1 = datetime(2025, 1, 2, tzinfo=timezone.utc)
        timestamps = [t0, t1]
        instrument_returns = {
            1: [(t0, 0.01), (t1, 0.02)],
            2: [(t0, 0.03), (t1, 0.04)],
        }
        matrix = build_factor_return_matrix(
            timestamps=timestamps,
            instrument_returns=instrument_returns,
            sector_peers=instrument_returns,
            macro_by_code={
                "cpi": [(t0, 100.0), (t1, 101.0)],
                "unemployment": [(t0, 5.0), (t1, 4.8)],
                "vix": [(t0, 20.0), (t1, 22.0)],
                "rate_cb": [(t0, 10.0), (t1, 10.5)],
                "dxy": [(t0, 100.0), (t1, 99.0)],
                "oil_brent": [(t0, 80.0), (t1, 82.0)],
            },
        )
        assert set(matrix.keys()) == set(FactorName)
        assert matrix[FactorName.MARKET_BETA] == pytest.approx([0.02, 0.03])


class TestFactorEngine:
    def test_synthetic_decomposition(self):
        random.seed(19)
        n = 120
        market = [random.gauss(0.0, 0.012) for _ in range(n)]
        sector = [random.gauss(0.0, 0.009) for _ in range(n)]
        noise = [random.gauss(0.0, 0.0008) for _ in range(n)]
        returns = [0.5 * m + 0.3 * s + e for m, s, e in zip(market, sector, noise)]
        timestamps = [datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(n)]

        engine = FactorEngine(config=FactorEngineConfig(window=60))
        rows = engine.estimate_from_series(
            instrument_id=42,
            timestamps=timestamps,
            instrument_returns=returns,
            factor_returns={
                FactorName.MARKET_BETA: market,
                FactorName.SECTOR_FACTOR: sector,
            },
        )
        assert rows
        latest_time = timestamps[-1]
        latest = [row for row in rows if row.time == latest_time]
        assert len(latest) == len(FactorName)
        market_row = next(row for row in latest if row.factor_name == FactorName.MARKET_BETA)
        sector_row = next(row for row in latest if row.factor_name == FactorName.SECTOR_FACTOR)
        assert market_row.beta == pytest.approx(0.5, abs=0.12)
        assert sector_row.beta == pytest.approx(0.3, abs=0.12)
        assert market_row.r_squared_of_model > 0.85
        assert sector_row.r_squared_of_model == market_row.r_squared_of_model

    def test_low_r_squared_preserved(self):
        random.seed(3)
        n = 70
        market = [random.gauss(0.0, 0.01) for _ in range(n)]
        returns = [random.gauss(0.0, 0.02) for _ in range(n)]
        timestamps = [datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(n)]
        engine = FactorEngine(config=FactorEngineConfig(window=30))
        rows = engine.estimate_from_series(
            instrument_id=1,
            timestamps=timestamps,
            instrument_returns=returns,
            factor_returns={FactorName.MARKET_BETA: market},
        )
        latest = [row for row in rows if row.time == timestamps[-1]]
        r_squared = latest[0].r_squared_of_model
        assert r_squared < 0.5
