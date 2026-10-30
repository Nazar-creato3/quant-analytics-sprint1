"""Unit tests for quant_math pure-function library (Prompt 17)."""
from __future__ import annotations

import math

import pytest

from datetime import date
from decimal import Decimal

from app.services.quant_math import (
    VaRMethod,
    apply_operations,
    convert_ccy,
    convert_roundtrip,
    correlation,
    covariance,
    euler_component_var,
    expected_shortfall,
    historical_volatility,
    log_return,
    money_weighted_return,
    portfolio_value,
    portfolio_variance,
    rolling_volatility,
    same_day_canonical,
    time_weighted_return,
    value_at_risk,
    weights_and_hhi,
)
from app.services.quant_math.book import Position, PriceQuote, next_day
from app.services.quant_math.core import _normal_ppf


class TestLogReturn:
    def test_known_values(self):
        assert log_return(110.0, 100.0) == pytest.approx(math.log(1.1))
        assert log_return(100.0, 100.0) == pytest.approx(0.0)

    def test_rejects_non_positive_prices(self):
        with pytest.raises(ValueError, match="strictly positive"):
            log_return(0.0, 100.0)
        with pytest.raises(ValueError, match="strictly positive"):
            log_return(100.0, -1.0)

    def test_rejects_nan_and_inf(self):
        with pytest.raises(ValueError, match="finite"):
            log_return(float("nan"), 100.0)
        with pytest.raises(ValueError, match="finite"):
            log_return(100.0, float("inf"))

    def test_rejects_non_numeric(self):
        with pytest.raises(TypeError):
            log_return("110", 100.0)  # type: ignore[arg-type]


class TestHistoricalVolatility:
    def test_matches_manual_calculation(self):
        returns = [0.01, -0.02, 0.015, 0.005, -0.01]
        mean_r = sum(returns) / len(returns)
        expected = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1))
        assert historical_volatility(returns) == pytest.approx(expected)

    def test_matches_sample_std_reference(self):
        returns = [0.02, -0.01, 0.03, -0.005, 0.012, -0.018]
        mean_r = sum(returns) / len(returns)
        reference = math.sqrt(sum((value - mean_r) ** 2 for value in returns) / (len(returns) - 1))
        assert historical_volatility(returns) == pytest.approx(reference)

    def test_single_observation_returns_zero(self):
        assert historical_volatility([0.05]) == 0.0

    def test_constant_series_returns_zero(self):
        assert historical_volatility([0.01, 0.01, 0.01, 0.01]) == 0.0

    def test_rejects_empty_returns(self):
        with pytest.raises(ValueError, match="empty"):
            historical_volatility([])

    def test_rejects_nan_and_inf(self):
        with pytest.raises(ValueError, match="NaN or inf"):
            historical_volatility([0.01, float("nan")])
        with pytest.raises(ValueError, match="NaN or inf"):
            historical_volatility([0.01, float("inf")])

    def test_rejects_non_numeric(self):
        with pytest.raises(TypeError):
            historical_volatility([0.01, "bad"])  # type: ignore[list-item]


class TestRollingVolatility:
    def test_window_two(self):
        returns = [0.01, 0.03, 0.02]
        result = rolling_volatility(returns, 2)
        assert math.isnan(result[0])
        assert result[1] == pytest.approx(historical_volatility([0.01, 0.03]))
        assert result[2] == pytest.approx(historical_volatility([0.03, 0.02]))

    def test_window_equals_length(self):
        returns = [0.01, -0.02, 0.015]
        result = rolling_volatility(returns, 3)
        assert math.isnan(result[0])
        assert math.isnan(result[1])
        assert result[2] == pytest.approx(historical_volatility(returns))

    def test_window_one_is_zero_after_first_point(self):
        returns = [0.01, 0.02, 0.03]
        result = rolling_volatility(returns, 1)
        assert result == [0.0, 0.0, 0.0]

    def test_window_larger_than_series_is_all_nan(self):
        returns = [0.01, 0.02]
        result = rolling_volatility(returns, 5)
        assert all(math.isnan(value) for value in result)

    def test_constant_window_is_zero(self):
        returns = [0.02, 0.02, 0.02, 0.02]
        result = rolling_volatility(returns, 3)
        assert result[-1] == 0.0

    def test_rejects_invalid_window(self):
        with pytest.raises(ValueError, match="window must be >= 1"):
            rolling_volatility([0.01, 0.02], 0)
        with pytest.raises(TypeError, match="integer"):
            rolling_volatility([0.01, 0.02], 2.5)  # type: ignore[arg-type]


class TestCovariance:
    def test_matches_manual_calculation(self):
        x = [1.0, 2.0, 3.0, 4.0]
        y = [2.0, 4.0, 5.0, 4.0]
        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)
        expected = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x))) / (len(x) - 1)
        assert covariance(x, y) == pytest.approx(expected)

    def test_matches_sample_covariance_reference(self):
        x = [0.01, -0.02, 0.015, 0.005]
        y = [0.02, -0.01, 0.01, 0.0]
        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)
        reference = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x))) / (len(x) - 1)
        assert covariance(x, y) == pytest.approx(reference)

    def test_single_pair_returns_zero(self):
        assert covariance([0.01], [0.02]) == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="same length"):
            covariance([0.01, 0.02], [0.01])


class TestCorrelation:
    def test_perfect_positive_correlation(self):
        x = [1.0, 2.0, 3.0, 4.0]
        y = [2.0, 4.0, 6.0, 8.0]
        assert correlation(x, y) == pytest.approx(1.0)

    def test_perfect_negative_correlation(self):
        x = [1.0, 2.0, 3.0, 4.0]
        y = [-2.0, -4.0, -6.0, -8.0]
        assert correlation(x, y) == pytest.approx(-1.0)

    def test_matches_manual_reference(self):
        x = [0.01, -0.02, 0.015, 0.005, -0.01]
        y = [0.02, -0.015, 0.01, 0.0, -0.005]
        reference = covariance(x, y) / (historical_volatility(x) * historical_volatility(y))
        assert correlation(x, y) == pytest.approx(reference)

    def test_constant_series_returns_zero(self):
        assert correlation([0.01, 0.01, 0.01], [0.02, 0.03, 0.04]) == 0.0
        assert correlation([0.01, 0.02, 0.03], [0.02, 0.02, 0.02]) == 0.0


class TestPortfolioVariance:
    def test_single_asset(self):
        assert portfolio_variance([1.0], [[0.04]]) == pytest.approx(0.04)

    def test_two_asset_manual(self):
        weights = [0.6, 0.4]
        sigma = [[0.04, 0.01], [0.01, 0.09]]
        expected = (
            weights[0] ** 2 * sigma[0][0]
            + 2 * weights[0] * weights[1] * sigma[0][1]
            + weights[1] ** 2 * sigma[1][1]
        )
        assert portfolio_variance(weights, sigma) == pytest.approx(expected)

    def test_three_asset_manual(self):
        weights = [0.5, 0.3, 0.2]
        sigma = [
            [0.04, 0.006, 0.002],
            [0.006, 0.09, 0.004],
            [0.002, 0.004, 0.16],
        ]
        expected = sum(
            weights[i] * weights[j] * sigma[i][j]
            for i in range(len(weights))
            for j in range(len(weights))
        )
        assert portfolio_variance(weights, sigma) == pytest.approx(expected)

    def test_rejects_dimension_mismatch(self):
        with pytest.raises(ValueError, match="row count"):
            portfolio_variance([0.5, 0.5], [[0.04]])
        with pytest.raises(ValueError, match="square"):
            portfolio_variance([0.5, 0.5], [[0.04, 0.01], [0.01]])

    def test_rejects_empty_weights(self):
        with pytest.raises(ValueError, match="empty"):
            portfolio_variance([], [])


class TestValueAtRisk:
    @pytest.mark.parametrize(
        ("returns", "alpha", "expected"),
        [
            ([-0.10, -0.05, 0.01, 0.02, 0.03], 0.80, 0.05),
            ([-0.03, -0.02, -0.01, 0.0, 0.01], 0.60, 0.01),
            ([-0.10, -0.05, 0.01, 0.02, 0.03], 0.95, 0.10),
        ],
    )
    def test_historical_var_matches_sorted_loss_quantile(
        self,
        returns: list[float],
        alpha: float,
        expected: float,
    ):
        losses = sorted(-value for value in returns)
        rank = max(0, min(len(losses) - 1, math.ceil(alpha * len(losses)) - 1))
        reference = losses[rank]
        assert reference == pytest.approx(expected)
        assert value_at_risk(returns, alpha, method=VaRMethod.HISTORICAL) == pytest.approx(expected)

    def test_historical_var_single_observation(self):
        assert value_at_risk([-0.07], 0.95, method=VaRMethod.HISTORICAL) == pytest.approx(0.07)

    def test_historical_var_all_positive_returns_is_zero(self):
        """Uptrend-only windows must not produce negative VaR (forecast tail-risk crash)."""
        returns = [0.002] * 40
        assert value_at_risk(returns, 0.95, method=VaRMethod.HISTORICAL) == 0.0

    def test_parametric_var_matches_normal_formula(self):
        returns = [0.01, -0.02, 0.015, 0.005, -0.01, 0.008]
        alpha = 0.95
        mean_r = sum(returns) / len(returns)
        std_r = historical_volatility(returns)
        z_score = _normal_ppf(1.0 - alpha)
        expected = -(mean_r + z_score * std_r)
        assert value_at_risk(returns, alpha, method=VaRMethod.PARAMETRIC) == pytest.approx(expected)

    def test_parametric_var_constant_returns(self):
        returns = [0.01, 0.01, 0.01, 0.01]
        alpha = 0.95
        expected = -0.01
        assert value_at_risk(returns, alpha, method=VaRMethod.PARAMETRIC) == pytest.approx(expected)

    def test_rejects_invalid_alpha(self):
        with pytest.raises(ValueError, match="alpha"):
            value_at_risk([0.01, -0.02], 0.0)
        with pytest.raises(ValueError, match="alpha"):
            value_at_risk([0.01, -0.02], 1.0)

    def test_rejects_unsupported_method(self):
        with pytest.raises(ValueError, match="Unsupported VaR method"):
            value_at_risk([0.01, -0.02], 0.95, method="monte_carlo")  # type: ignore[arg-type]


class TestExpectedShortfall:
    def test_tail_average_beyond_var(self):
        returns = [-0.10, -0.08, -0.02, 0.01, 0.02, 0.03]
        alpha = 0.95
        var_value = value_at_risk(returns, alpha, method=VaRMethod.HISTORICAL)
        tail = [-value for value in returns if value <= -var_value]
        expected = sum(tail) / len(tail)
        assert expected_shortfall(returns, alpha, var_value) == pytest.approx(expected)

    def test_no_tail_observations_returns_var(self):
        returns = [0.01, 0.02, 0.03]
        assert expected_shortfall(returns, 0.95, 0.50) == pytest.approx(0.50)

    def test_rejects_negative_var(self):
        with pytest.raises(ValueError, match="non-negative"):
            expected_shortfall([0.01, -0.02], 0.95, -0.01)


class TestNormalPpf:
    @pytest.mark.parametrize(
        ("probability", "expected"),
        [
            (0.5, 0.0),
            (0.975, 1.959963984540054),
            (0.025, -1.959963984540054),
        ],
    )
    def test_matches_reference_quantiles(self, probability: float, expected: float):
        assert _normal_ppf(probability) == pytest.approx(expected, abs=5e-3)

    def test_rejects_invalid_probability(self):
        with pytest.raises(ValueError, match="open interval"):
            _normal_ppf(0.0)
        with pytest.raises(ValueError, match="open interval"):
            _normal_ppf(1.0)

    def test_upper_tail_probability(self):
        assert _normal_ppf(0.99) == pytest.approx(2.326347874040841, abs=5e-3)


class TestValidationHelpers:
    def test_returns_rejects_non_sequence(self):
        with pytest.raises(TypeError, match="sequence"):
            historical_volatility(123)  # type: ignore[arg-type]

    def test_returns_rejects_string_sequence(self):
        with pytest.raises(TypeError, match="sequence"):
            historical_volatility("abc")  # type: ignore[arg-type]

    def test_portfolio_variance_rejects_non_finite_matrix(self):
        with pytest.raises(ValueError, match="finite"):
            portfolio_variance([0.5, 0.5], [[0.04, float("nan")], [0.01, 0.09]])

    def test_portfolio_variance_rejects_non_finite_weights(self):
        with pytest.raises(ValueError, match="finite"):
            portfolio_variance([0.5, float("inf")], [[0.04, 0.01], [0.01, 0.09]])


class TestBookMath:
    def test_fx_roundtrip_within_rounding(self):
        amount = Decimal("100.12")
        back = convert_roundtrip(amount, Decimal("95.5"))
        assert abs(back - amount) <= Decimal("0.00000002")
        assert convert_ccy(Decimal("2"), Decimal("10")) == Decimal("20.00000000")

    def test_fx_zero_rate_rejected(self):
        with pytest.raises(ValueError, match="non-zero"):
            convert_roundtrip(Decimal("1"), Decimal("0"))

    def test_future_nav_is_variation_not_notional(self):
        pos = Position(
            symbol="Si",
            qty=Decimal("1"),
            ccy="RUB",
            instrument="future",
            variation_margin=Decimal("12"),
        )
        quote = PriceQuote(
            symbol="Si",
            as_of=date(2024, 7, 10),
            price=Decimal("90000"),
            ccy="RUB",
            source="t",
            price_type="official_close",
        )
        assert portfolio_value([pos], {"Si": quote}, {"RUB": Decimal("1")}, Decimal("50")) == Decimal("62.00000000")

    def test_missing_price_and_zero_value(self):
        pos = Position(symbol="X", qty=Decimal("1"), ccy="RUB", instrument="equity")
        with pytest.raises(KeyError):
            portfolio_value([pos], {}, {"RUB": Decimal("1")}, Decimal("0"))
        with pytest.raises(ValueError, match="zero"):
            weights_and_hhi([], {}, {}, Decimal("0"))

    def test_twr_and_mwr_known(self):
        assert time_weighted_return([(Decimal("100"), Decimal("110"))]) == Decimal("0.10000000")
        with pytest.raises(ValueError, match="positive"):
            time_weighted_return([(Decimal("0"), Decimal("1"))])
        rate = money_weighted_return(
            [(date(2024, 1, 1), Decimal("-100")), (date(2024, 1, 31), Decimal("110"))]
        )
        assert rate > 0
        with pytest.raises(ValueError, match="two"):
            money_weighted_return([(date(2024, 1, 1), Decimal("-1"))])

    def test_mwr_bisection_when_newton_does_not_root(self):
        positive = money_weighted_return(
            [(date(2024, 1, 1), Decimal("10")), (date(2025, 1, 1), Decimal("10"))]
        )
        negative = money_weighted_return(
            [(date(2024, 1, 1), Decimal("-10")), (date(2025, 1, 1), Decimal("-10"))]
        )
        assert isinstance(positive, Decimal)
        assert isinstance(negative, Decimal)

    def test_euler_sums_to_portfolio_var(self):
        weights = [0.5, 0.5]
        sigma = [[0.04, 0.0], [0.0, 0.09]]
        var = 0.2
        parts = euler_component_var(weights, sigma, var)
        assert sum(parts) == pytest.approx(var)
        assert euler_component_var([1.0], [[0.0]], 0.5) == [0.0]

    def test_apply_operations_and_idempotence(self):
        ops = [
            {"op_id": "1", "as_of": "2024-01-01", "kind": "deposit", "amount_base": 200},
            {"op_id": "2", "as_of": "2024-01-01", "kind": "buy", "symbol": "SBER", "qty": "1", "amount_base": "100", "ccy": "RUB", "instrument": "equity"},
            {"op_id": "3", "as_of": "2024-01-02", "kind": "sell", "symbol": "SBER", "qty": "1", "amount_base": "110", "ccy": "RUB", "instrument": "equity"},
            {"op_id": "4", "as_of": "2024-01-03", "kind": "withdraw", "amount_base": "-10"},
            {"op_id": "5", "as_of": "2024-01-04", "kind": "deposit", "amount_base": "100"},
            {"op_id": "6", "as_of": "2024-01-04", "kind": "buy", "symbol": "OFZ", "qty": "1", "amount_base": "50", "ccy": "RUB", "instrument": "bond"},
            {"op_id": "7", "as_of": "2024-01-04", "kind": "split", "symbol": "OFZ", "factor": "2"},
            {"op_id": "8", "as_of": "2024-01-04", "kind": "set_aci", "symbol": "OFZ", "aci": "1.5"},
            {"op_id": "9", "as_of": "2024-01-04", "kind": "dividend", "amount_base": 1.0},
            {"op_id": "10", "as_of": "2024-01-04", "kind": "coupon", "amount_base": "1"},
            {"op_id": "11", "as_of": "2024-01-04", "kind": "buy", "symbol": "Si", "qty": "1", "amount_base": "0", "ccy": "RUB", "instrument": "future"},
            {"op_id": "12", "as_of": "2024-01-04", "kind": "set_vm", "symbol": "Si", "variation_margin": "3", "amount_base": "0"},
        ]
        first = apply_operations(ops)
        second = apply_operations(ops)
        assert first.cash_base == Decimal("252")
        assert {p.symbol for p in first.positions} == {"OFZ", "Si"}
        assert second.cash_base == first.cash_base
        assert second.ops_hash == first.ops_hash
        shuffled = list(reversed(ops))
        canon = same_day_canonical(shuffled)
        assert [x["op_id"] for x in canon] == [str(i) for i in range(1, 13)]
        assert apply_operations(canon).cash_base == first.cash_base
        mixed = same_day_canonical(
            [{"as_of": "2024-01-01", "op_id": "z"}, {"as_of": "2024-01-01", "op_id": "2"}]
        )
        assert [row["op_id"] for row in mixed] == ["2", "z"]
        with pytest.raises(ValueError, match="unknown"):
            apply_operations([{"as_of": "2024-01-01", "kind": "teleport"}])
        assert next_day(date(2024, 1, 31)) == date(2024, 2, 1)

    def test_weights_hhi_single_name(self):
        pos = Position(symbol="SBER", qty=Decimal("1"), ccy="RUB", instrument="equity")
        quote = PriceQuote(
            symbol="SBER",
            as_of=date(2024, 1, 31),
            price=Decimal("110"),
            ccy="RUB",
            source="t",
            price_type="official_close",
        )
        weights, hhi = weights_and_hhi([pos], {"SBER": quote}, {"RUB": Decimal("1")}, Decimal("0"))
        assert weights["SBER"] == Decimal("1")
        assert hhi == Decimal("1")
