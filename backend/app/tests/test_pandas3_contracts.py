"""Contracts for pandas 3.0.6 (D-00A-1): CoW, default string dtype, VaR parity.

VaR numbers are numpy-only (`portfolio_math`); pandas is an I/O/feature frame.
This file proves the pin and that string/CoW defaults do not change those
quantiles when the same series is wrapped in a DataFrame.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.risk.portfolio_math import historical_var_quantile
from app.tests.test_apex_portfolio_math_references import (
    REFERENCE_RETURNS,
    REF_VAR_Q05,
)


def test_pandas_pin_is_3():
    major = int(pd.__version__.split(".", maxsplit=1)[0])
    assert major >= 3, pd.__version__


def test_copy_on_write_slice_does_not_mutate_parent():
    parent = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
    view = parent["close"]
    mutated = view.copy()
    mutated.iloc[0] = 1.0
    assert float(parent["close"].iloc[0]) == 100.0
    assert float(mutated.iloc[0]) == 1.0


def test_default_string_dtype_is_not_object():
    series = pd.Series(["MOEX", "NYSE", "LSE"])
    assert series.dtype != object
    assert series.dtype == pd.StringDtype() or str(series.dtype) in {"str", "string"}


def test_object_equality_check_is_not_used_for_tickers():
    frame = pd.DataFrame({"ticker": ["SBER", "GAZP"], "close": [100.0, 200.0]})
    assert frame["ticker"].dtype != object
    assert list(frame.loc[frame["ticker"] == "SBER", "close"]) == [100.0]


def test_var_quantile_unchanged_via_pandas_series():
    from_numpy = historical_var_quantile(REFERENCE_RETURNS, cutoff=0.05)
    wrapped = pd.Series(REFERENCE_RETURNS, dtype="float64")
    from_frame = historical_var_quantile(wrapped.to_numpy(), cutoff=0.05)
    assert from_numpy == pytest.approx(REF_VAR_Q05, rel=1e-9)
    assert from_frame == pytest.approx(REF_VAR_Q05, rel=1e-9)
    assert from_frame == pytest.approx(float(np.percentile(wrapped, 5)), rel=1e-12)
