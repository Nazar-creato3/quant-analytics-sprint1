"""Regression tests for terminal forecast numeric integrity (GOOGL fixture)."""
from __future__ import annotations

import numpy as np
import pytest

from app.services.forecast.distribution import build_forecast_distribution
from app.services.forecast.global_macro_view import (
    ETF_INDEX_ALIASES,
    _align_dated_returns,
    _compute_correlation_matrix,
    _returns_from_dated_closes,
)
from app.services.forecast.numeric_integrity import validate_tool_response
from app.services.forecast.types import ForecastDirection
from app.services.prediction_hierarchy.hierarchy_validation import HierarchyValidationEngine
from app.services.track_record.calibration_chart import build_track_record_chart_data
from app.services.track_record.reference_series import trend_prices


def _googl_like_prices(count: int = 120, drift: float = 0.08) -> list[float]:
    """Synthetic GOOGL-like uptrend with noise."""
    rng = np.random.default_rng(42)
    prices = [100.0]
    for _ in range(count - 1):
        prices.append(prices[-1] * (1.0 + drift / 100.0 + rng.normal(0, 0.012)))
    return prices


class TestForecastDistributionConsistency:
    def test_directional_forecast_produces_asymmetric_interval(self):
        prices = _googl_like_prices()
        dist = build_forecast_distribution(
            prices=prices,
            momentum_score=0.72,
            direction=ForecastDirection.BULLISH,
        )
        assert dist.point_direction == "increase"
        assert dist.signal_strength >= 0.35
        assert not dist.symmetric_interval
        assert dist.p90 > abs(dist.p10)

    def test_weak_signal_flagged_low_confidence(self):
        prices = _googl_like_prices()
        dist = build_forecast_distribution(
            prices=prices,
            momentum_score=0.19,
            direction=ForecastDirection.BEARISH,
        )
        assert dist.low_confidence
        report = validate_tool_response("get_forecast_distribution", dist.to_dict())
        assert report.ok or any(v.code == "weak_signal_no_flag" for v in report.violations)

    def test_insufficient_data_not_zero_pretending_computed(self):
        dist = build_forecast_distribution(
            prices=[100.0, 101.0],
            momentum_score=0.5,
            direction=ForecastDirection.NEUTRAL,
        )
        assert dist.insufficient_data
        assert dist.data_quality.get("returns") == "insufficient_data"


class TestCorrelationMatrix:
    def test_spy_gspc_high_correlation_on_aligned_dates(self):
        """Regression: ETF vs tracked index must correlate > 0.95 on co-moving data."""
        base = 400.0
        dated_spy: dict[str, float] = {}
        dated_gspc: dict[str, float] = {}
        for i in range(60):
            date = f"2024-01-{i + 1:02d}" if i < 31 else f"2024-02-{i - 30:02d}"
            if i >= 59:
                date = "2024-02-28"
            move = 0.001 * (1 if i % 3 else -1)
            base *= 1.0 + move
            dated_spy[date] = base
            dated_gspc[date] = base * 1.0001

        aligned = _align_dated_returns(
            {
                "SPY": _returns_from_dated_closes(dated_spy),
                "^GSPC": _returns_from_dated_closes(dated_gspc),
            }
        )
        matrix, symbols = _compute_correlation_matrix(aligned)
        assert "SPY" in symbols and "^GSPC" in symbols
        corr = matrix["SPY"]["^GSPC"]
        assert corr > 0.95, f"SPY/^GSPC correlation {corr} expected > 0.95"

    def test_date_alignment_not_tail_mismatch(self):
        """Misaligned tails must not be used — only shared dates."""
        spy_only = {f"2024-03-{i:02d}": 100.0 + i for i in range(1, 21)}
        gspc_only = {f"2024-04-{i:02d}": 200.0 + i for i in range(1, 21)}
        aligned = _align_dated_returns(
            {
                "SPY": _returns_from_dated_closes(spy_only),
                "^GSPC": _returns_from_dated_closes(gspc_only),
            }
        )
        assert aligned == {}


class TestRollingAccuracy:
    def test_windows_have_distinct_accuracy_or_mae(self):
        prices = list(trend_prices(100.0, 0.2, 140)) + list(trend_prices(128.0, -0.15, 40))
        engine = HierarchyValidationEngine()
        report = engine.run(instrument_id=999, prices=prices, volumes=[1.0] * len(prices))
        assert report.rolling_window_metrics
        accuracies = [m.regime_match_accuracy for m in report.rolling_window_metrics]
        maes = [m.mae for m in report.rolling_window_metrics]
        assert len(set(round(a, 3) for a in accuracies)) > 1 or len(set(round(m, 3) for m in maes)) > 1

    def test_calibration_chart_no_identical_stub(self):
        chart = build_track_record_chart_data()
        if len(chart.rolling_accuracy) >= 2:
            accs = [p.regime_match_accuracy for p in chart.rolling_accuracy]
            maes = [p.mae for p in chart.rolling_accuracy]
            if len(set(round(m, 4) for m in maes)) > 1:
                assert len(set(round(a, 4) for a in accs)) > 1


class TestNumericIntegrityValidation:
    def test_rejects_low_etf_index_correlation(self):
        payload = {
            "correlation_matrix": {
                "SPY": {"SPY": 1.0, "^GSPC": 0.12},
                "^GSPC": {"SPY": 0.12, "^GSPC": 1.0},
            }
        }
        report = validate_tool_response("get_correlation_matrix", payload)
        assert not report.ok
        assert any(v.code == "etf_index_correlation_low" for v in report.violations)

    def test_rejects_identical_accuracy_differing_mae(self):
        payload = {
            "windows": [
                {"window_days": 30, "regime_match_accuracy": 0.5, "mae": 0.475},
                {"window_days": 90, "regime_match_accuracy": 0.5, "mae": 0.544},
                {"window_days": 365, "regime_match_accuracy": 0.5, "mae": 0.453},
            ]
        }
        report = validate_tool_response("get_rolling_accuracy", payload)
        assert not report.ok
        assert any(v.code == "identical_accuracy_differing_mae" for v in report.violations)

    def test_sanitize_strips_deprecated_aliases_for_llm(self):
        from app.services.forecast.numeric_integrity import sanitize_tool_payload_for_llm

        raw = {
            "ticker": "AAPL",
            "windows": [
                {
                    "window_days": 30,
                    "regime_match_accuracy": 0.23,
                    "directional_accuracy": 0.23,
                    "mae": 0.475,
                }
            ],
            "live_vs_backtest_gap": 0.47,
        }
        cleaned = sanitize_tool_payload_for_llm("get_rolling_accuracy", raw)
        assert "directional_accuracy" not in cleaned
        assert "live_vs_backtest_gap" not in cleaned
        assert cleaned["windows"][0]["metric_label_ru"] == "точность классификации режима (тест)"
        assert "metric_glossary_ru" in cleaned


class TestToolLayerE2E:
    def test_new_tools_registered(self):
        from app.services.chat.tools import TOOL_SCHEMAS

        names = {s["function"]["name"] for s in TOOL_SCHEMAS}
        assert "get_forecast_distribution" in names
        assert "get_rolling_accuracy" in names
        assert "get_correlation_matrix" in names

    def test_validation_applied_to_distribution_payload(self):
        from app.services.forecast.numeric_integrity import apply_validation_to_payload

        prices = _googl_like_prices()
        dist = build_forecast_distribution(
            prices=prices,
            momentum_score=0.62,
            direction=ForecastDirection.BULLISH,
        )
        payload = apply_validation_to_payload(
            "get_forecast_distribution",
            {"ticker": "GOOGL", **dist.to_dict()},
        )
        assert payload["ticker"] == "GOOGL"
        assert "integrity" in payload
        assert payload["integrity"]["ok"] is True


class TestMetricValidity:
    def test_missing_upstream_marks_metrics_invalid_not_zero(self):
        from app.services.forecast.probability_map import build_metric_validity
        from app.services.prediction_hierarchy.types import (
            ActionForecast,
            ActionRecommendation,
            DistributionForecast,
            ForecastOutput,
            IntervalForecast,
            PointForecast,
            PointMagnitudeClass,
            RiskForecastLayer,
            ScenarioForecast,
        )

        hierarchy = ForecastOutput(
            instrument_id=1,
            symbol="TEST",
            as_of="2026-01-01",
            point_forecast=PointForecast(
                magnitude_class=PointMagnitudeClass.NEUTRAL,
                expected_return_sign=0,
                momentum_score=0.5,
            ),
            interval_forecast=IntervalForecast(
                horizon_days=10,
                p10=0.0,
                p90=0.0,
                rolling_volatility=0.0,
                confidence_multiplier=1.645,
                plain_language_summary="Недостаточно истории для интервала доходности (insufficient_data).",
            ),
            distribution_forecast=DistributionForecast(
                p5=0.0,
                p25=0.0,
                p50=0.0,
                p75=0.0,
                p95=0.0,
                method="insufficient_data",
            ),
            scenario_forecast=ScenarioForecast(scenarios=(), scenario_dispersion=0.0),
            risk_forecast=RiskForecastLayer(
                instrument_metrics={"composite_risk_score": 0.2},
                portfolio_metrics={},
            ),
            action_forecast=ActionForecast(
                recommendation=ActionRecommendation.HOLD,
                reason="test",
                rule_id="test",
            ),
            calibrated_confidence=0.5,
            high_confidence=False,
        )
        validity = build_metric_validity(hierarchy)
        assert validity["interval_p10"] is False
        assert validity["interval_p90"] is False
        assert validity["volatility_expansion_probability"] is False


class TestCalibrationRollingConsistency:
    def test_rolling_accuracy_within_calibration_bar_range(self):
        from app.services.track_record.calibration_chart import build_track_record_chart_data
        from app.services.track_record.reference_series import build_reference_benchmarks

        refs = build_reference_benchmarks()
        chart = build_track_record_chart_data(benchmarks=(refs[0],))
        if not chart.calibration_bins or not chart.rolling_accuracy:
            pytest.skip("insufficient benchmark data")
        bin_min = min(b.observed_frequency for b in chart.calibration_bins)
        bin_max = max(b.observed_frequency for b in chart.calibration_bins)
        roll_avg = sum(p.regime_match_accuracy for p in chart.rolling_accuracy) / len(
            chart.rolling_accuracy
        )
        assert bin_min - 0.2 <= roll_avg <= bin_max + 0.2


class TestDirectionThreshold:
    def test_weak_bearish_momentum_yields_neutral_point(self):
        from app.services.forecast.types import ForecastDirection, ForecastSignals, InstrumentForecast
        from app.services.prediction_hierarchy.forecast_output import ForecastOutputBuilder

        builder = ForecastOutputBuilder()
        forecast = InstrumentForecast(
            instrument_id=1,
            regime_distribution={"bearish_trend": 0.6, "choppy_range": 0.4},
            risk_flags=(),
            confidence=0.4,
            contributing_factors=(),
            composite_risk_score=0.3,
            signals=ForecastSignals(
                short_term_momentum=0.19,
                momentum_direction=ForecastDirection.BEARISH,
                tail_risk_score=0.2,
                volatility_expansion_probability=0.2,
                correlation_shift_score=0.1,
                liquidity_deterioration_score=0.1,
                event_impact_score=0.1,
            ),
            dominant_regime="bearish_trend",
        )
        prices = _googl_like_prices()
        point = builder._build_point_forecast(forecast, "GOOGL", prices)
        assert point.magnitude_class.value == "neutral"
        assert point.expected_return_sign == 0
        assert "неопределённо" in point.plain_language_summary.lower()

    def test_strong_bullish_momentum_keeps_nonzero_sign_despite_low_confidence_flag(self):
        """SINGLE_NAME low_confidence must not zero expected_return_sign for snapshots."""
        from app.services.forecast.distribution import SINGLE_NAME_DIRECTION_LOW_CONFIDENCE
        from app.services.forecast.types import ForecastDirection, ForecastSignals, InstrumentForecast
        from app.services.prediction_hierarchy.forecast_output import ForecastOutputBuilder

        assert SINGLE_NAME_DIRECTION_LOW_CONFIDENCE is True
        builder = ForecastOutputBuilder()
        forecast = InstrumentForecast(
            instrument_id=1,
            regime_distribution={"bullish_trend": 0.7, "choppy_range": 0.3},
            risk_flags=(),
            confidence=0.7,
            contributing_factors=(),
            composite_risk_score=0.3,
            signals=ForecastSignals(
                short_term_momentum=0.72,
                momentum_direction=ForecastDirection.BULLISH,
                tail_risk_score=0.2,
                volatility_expansion_probability=0.2,
                correlation_shift_score=0.1,
                liquidity_deterioration_score=0.1,
                event_impact_score=0.1,
            ),
            dominant_regime="bullish_trend",
        )
        point = builder._build_point_forecast(forecast, "AAPL", _googl_like_prices())
        assert point.expected_return_sign == 1
        assert point.magnitude_class.value in {"up", "strong_up"}


class TestAgenticInvalidMetricPolicy:
    def test_system_prompt_requires_invalid_metric_disclosure(self):
        from app.services.chat.advisor_prompt import build_agentic_chat_system

        system = build_agentic_chat_system(mode="thinking")
        assert "is_valid=false" in system.lower()
        assert "validation_failed" in system.lower()


class TestRegimeAliasPairs:
    def test_etf_index_aliases_defined(self):
        assert ETF_INDEX_ALIASES["SPY"] == "^GSPC"
