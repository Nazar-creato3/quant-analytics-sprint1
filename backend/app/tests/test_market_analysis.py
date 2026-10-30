"""Unit tests for market analysis system (spec Sections 1, 3, 5, 7.1)."""
from __future__ import annotations

import math
import random
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.schemas.ticker_analysis import TickerAnalysisPayload
from app.services.market_analysis.assembler import build_ticker_analysis_payload
from app.services.market_analysis.risk_metrics import (
    compute_max_drawdown,
    compute_risk_metrics_from_prices,
    returns_from_prices,
)
from app.services.market_analysis.scenarios import apply_factor_shock, run_stress_scenarios
from app.services.market_analysis.style_factors import (
    RawStyleSignals,
    compute_raw_style_signals,
    compute_style_factor_exposures,
    cross_sectional_zscore,
)
from app.services.prediction_hierarchy.types import ForecastOutput


class TestCrossSectionalZscore:
    def test_standardizes_peers(self):
        raw = {"a": 1.0, "b": 2.0, "c": 3.0}
        z = cross_sectional_zscore(raw)
        assert z["a"] == pytest.approx(-1.0, abs=0.01)
        assert z["b"] == pytest.approx(0.0, abs=0.01)
        assert z["c"] == pytest.approx(1.0, abs=0.01)

    def test_single_observation_zero(self):
        assert cross_sectional_zscore({"x": 5.0}) == {"x": 0.0}

    def test_nulls_preserved(self):
        z = cross_sectional_zscore({"a": 1.0, "b": None, "c": 3.0})
        assert z["b"] is None
        assert z["a"] is not None


class TestStyleFactorSignals:
    def test_value_from_pe(self):
        prices = [100.0 + i * 0.5 for i in range(280)]
        signals = compute_raw_style_signals(
            prices=prices,
            volumes=[1_000_000.0] * len(prices),
            fundamentals={"pe_ratio": 10.0, "market_cap": 1e12, "roe": 0.15},
        )
        assert signals.value == pytest.approx(0.1)
        assert signals.size is not None
        assert signals.size < 0

    def test_momentum_requires_history(self):
        prices = [100.0] * 50
        signals = compute_raw_style_signals(prices=prices, volumes=[])
        assert signals.momentum is None

    def test_cross_sectional_exposures(self):
        target = RawStyleSignals(value=0.1, momentum=0.05, size=-20.0, quality=0.12)
        peers = [
            RawStyleSignals(value=0.08, momentum=0.02, size=-21.0, quality=0.10),
            RawStyleSignals(value=0.12, momentum=0.08, size=-19.0, quality=0.14),
        ]
        exposures = compute_style_factor_exposures(target_signals=target, peer_signals=peers)
        assert exposures["value"] is not None
        assert exposures["momentum"] is not None


class TestRiskMetrics:
    def _synthetic_prices(self, n: int = 120, drift: float = 0.0002, vol: float = 0.01) -> list[float]:
        random.seed(42)
        price = 100.0
        prices = [price]
        for _ in range(n - 1):
            price *= math.exp(drift + random.gauss(0, vol))
            prices.append(price)
        return prices

    def test_var_cvar_positive_loss_magnitude(self):
        prices = self._synthetic_prices()
        metrics = compute_risk_metrics_from_prices(prices)
        assert metrics.var_95 is not None
        assert metrics.cvar_95 is not None
        assert metrics.var_95 >= 0
        assert metrics.cvar_95 >= metrics.var_95

    def test_annualized_volatility(self):
        prices = self._synthetic_prices()
        metrics = compute_risk_metrics_from_prices(prices)
        assert metrics.volatility is not None
        assert metrics.volatility > 0

    def test_beta_with_benchmark(self):
        asset = self._synthetic_prices(150, drift=0.0003)
        bench = self._synthetic_prices(150, drift=0.0001)
        metrics = compute_risk_metrics_from_prices(asset, benchmark_prices=bench)
        assert metrics.beta is not None
        assert metrics.tracking_error is not None

    def test_max_drawdown(self):
        prices = [100.0, 110.0, 90.0, 95.0]
        assert compute_max_drawdown(prices) == pytest.approx(0.181818, abs=0.001)

    def test_insufficient_data_returns_nulls(self):
        metrics = compute_risk_metrics_from_prices([100.0, 101.0])
        assert metrics.var_95 is None


class TestScenarios:
    def test_historical_replay_uses_exposures(self):
        exposures = {"value": 0.5, "momentum": -0.3, "market_beta": 1.1}
        results = run_stress_scenarios(exposures)
        assert "2008_replay" in results
        assert results["2008_replay"] is not None
        assert results["rate_shock_200bps"] is not None

    def test_apply_factor_shock(self):
        impact = apply_factor_shock({"momentum": 1.0}, {"momentum": -0.10})
        assert impact == pytest.approx(-0.10)


class TestPayloadAssembly:
    @pytest.fixture
    def trained_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODEL_DIR", str(tmp_path))
        import app.services.ml.model as model_module

        monkeypatch.setattr(model_module, "MODEL_DIR", tmp_path)
        rows = []
        price = 100.0
        for i in range(320):
            price *= math.exp(0.0003 + 0.012 * math.sin(i / 7))
            rows.append(
                {
                    "open": price * 0.999,
                    "high": price * 1.005,
                    "low": price * 0.995,
                    "close": price,
                    "volume": 500_000.0 + i * 1000,
                }
            )
        df = pd.DataFrame(rows)
        from app.services.ml.features import compute_features
        from app.services.ml.model import train_direction_model

        train_direction_model(compute_features(df), already_featured=True)
        model_module._classifier = None
        return tmp_path

    @pytest.mark.asyncio
    async def test_build_payload_structure(self, trained_model):
        prices = [100.0 + math.sin(i / 10) + i * 0.05 for i in range(280)]
        volumes = [500_000.0] * len(prices)
        bench = [200.0 + i * 0.03 for i in range(280)]

        mock_db = AsyncMock()
        hierarchy = MagicMock(spec=ForecastOutput)
        hierarchy.calibrated_confidence = 0.72

        with (
            patch(
                "app.services.market_analysis.assembler.load_forecast_price_series",
                new=AsyncMock(return_value=(prices, volumes, None)),
            ),
            patch(
                "app.services.market_analysis.assembler.fetch_fundamentals",
                new=AsyncMock(
                    return_value={
                        "market_cap": 5e11,
                        "pe_ratio": 15.0,
                        "roe": 0.18,
                        "averageVolume": 2e6,
                    }
                ),
            ),
            patch(
                "app.services.market_analysis.assembler._load_sector_peers",
                new=AsyncMock(return_value=("Technology", [])),
            ),
            patch(
                "app.services.market_analysis.assembler._load_regression_exposures",
                new=AsyncMock(return_value={"market_beta": 1.05, "momentum": 0.2}),
            ),
            patch(
                "app.services.market_analysis.assembler._load_benchmark_prices",
                new=AsyncMock(return_value=bench),
            ),
            patch(
                "app.services.market_analysis.assembler._peer_comparison",
                new=AsyncMock(
                    return_value=__import__(
                        "app.schemas.ticker_analysis", fromlist=["PeerComparison"]
                    ).PeerComparison(sector="Technology", peer_count=3, sector_avg_score=0.65)
                ),
            ),
        ):
            payload = await build_ticker_analysis_payload(
                "AAPL",
                mock_db,
                instrument_id=1,
                hierarchy=hierarchy,
            )

        assert isinstance(payload, TickerAnalysisPayload)
        assert payload.ticker == "AAPL"
        assert payload.ml_score == pytest.approx(0.72)
        assert payload.shap_available is True
        assert payload.shap_top_factors is not None
        assert len(payload.shap_top_factors) >= 1
        assert payload.shap_top_factors[0].feature
        assert "value" in payload.factor_exposures
        assert payload.risk_metrics.get("var_95") is not None
        assert "2008_replay" in payload.scenario_results
        assert payload.peer_comparison.sector == "Technology"
        assert payload.factor_implied_covariance is not None

    def test_returns_from_prices(self):
        returns = returns_from_prices([100.0, 110.0])
        assert len(returns) == 1
        assert returns[0] == pytest.approx(math.log(1.1))
