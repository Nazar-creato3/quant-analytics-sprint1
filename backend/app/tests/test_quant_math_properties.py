"""Hypothesis properties for core book/risk (Prompt 01B)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.quant_math import (
    VaRMethod,
    apply_operations,
    convert_roundtrip,
    euler_component_var,
    expected_shortfall,
    money_weighted_return,
    same_day_canonical,
    time_weighted_return,
    value_at_risk,
)


@settings(max_examples=40)
@given(st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False))
def test_twr_independent_of_deposit_scale_single_asset(scale: float):
    start = Decimal("100") * Decimal(str(round(scale, 6)))
    end = start * Decimal("1.1")
    assert time_weighted_return([(start, end)]) == Decimal("0.10000000")


@settings(max_examples=30)
@given(st.floats(min_value=0.2, max_value=5.0, allow_nan=False, allow_infinity=False))
def test_scale_positions_leaves_return_scales_var(scale: float):
    returns = [-0.04, -0.02, 0.01, 0.03, 0.00]
    base_var = value_at_risk(returns, 0.8, method=VaRMethod.HISTORICAL)
    pnl = [-r * 100.0 * scale for r in returns]
    scaled_var = value_at_risk([-x / (100.0 * scale) for x in pnl], 0.8, method=VaRMethod.HISTORICAL)
    assert scaled_var == pytest.approx(base_var)
    assert base_var * scale == pytest.approx(base_var * scale)


@settings(max_examples=25)
@given(st.lists(st.floats(min_value=-0.2, max_value=0.2, allow_nan=False, allow_infinity=False), min_size=8, max_size=20))
def test_var_monotone_and_es_not_below_var(returns: list[float]):
    if all(x == returns[0] for x in returns):
        return
    low = value_at_risk(returns, 0.80, method=VaRMethod.HISTORICAL)
    high = value_at_risk(returns, 0.95, method=VaRMethod.HISTORICAL)
    assert high >= low - 1e-12
    assert expected_shortfall(returns, 0.95, high) >= high - 1e-12


def test_euler_components_sum_to_var():
    parts = euler_component_var([0.4, 0.6], [[0.04, 0.01], [0.01, 0.09]], 0.15)
    assert sum(parts) == pytest.approx(0.15)


def test_same_day_permutation_and_reload():
    ops = [
        {"op_id": "a", "as_of": "2024-01-01", "kind": "deposit", "amount_base": "50"},
        {"op_id": "b", "as_of": "2024-01-01", "kind": "deposit", "amount_base": "70"},
    ]
    left = apply_operations(same_day_canonical(ops))
    right = apply_operations(same_day_canonical(list(reversed(ops))))
    assert left.cash_base == right.cash_base
    assert apply_operations(ops).cash_base == apply_operations(list(ops)).cash_base


@given(st.decimals(min_value="1", max_value="10000", allow_nan=False, places=2), st.decimals(min_value="0.1", max_value="200", allow_nan=False, places=4))
@settings(max_examples=30)
def test_fx_roundtrip(amount: Decimal, rate: Decimal):
    back = convert_roundtrip(amount, rate)
    assert abs(back - amount) <= Decimal("0.0000001")


def test_mwr_one_year_doubling():
    rate = money_weighted_return(
        [(date(2020, 1, 1), Decimal("-100")), (date(2021, 1, 1), Decimal("200"))]
    )
    assert abs(rate - Decimal("1")) < Decimal("0.01")


def test_twr_with_mid_deposit_matches_price_path():
    # 100 → 110 then deposit 90 → 200, then 200 → 220 (same +10%).
    linked = time_weighted_return([(Decimal("100"), Decimal("110")), (Decimal("200"), Decimal("220"))])
    assert linked == Decimal("0.21000000")
    assert (date(2024, 1, 1) + timedelta(days=1)).day == 2
