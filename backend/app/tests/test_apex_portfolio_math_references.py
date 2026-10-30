"""Golden-reference tests for Apex vendored portfolio_math.

Reference numbers were computed offline from documented empyrical formulas
(``np.percentile``, partition CVaR, cumulative drawdown on wealth index).
Tests require no network and no empyrical/pyfolio imports.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys

import numpy as np
import pytest

from app.services.risk.portfolio_math import (
    cumulative_return,
    historical_var_es,
    historical_var_quantile,
    max_drawdown,
    multi_factor_betas,
    ols_alpha_beta,
    simple_returns,
)
from app.services.risk.portfolio_math.var import conditional_var_quantile

# 50 daily returns — fixed seed-free deterministic fixture.
REFERENCE_RETURNS = np.array(
    [
        -0.08, -0.06, -0.05, -0.04, -0.03, -0.02, -0.01, 0.0, 0.01, 0.02,
        0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12,
        0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21, 0.22,
        0.23, 0.24, 0.25, 0.26, 0.27, 0.28, 0.29, 0.30, 0.31, 0.32,
        0.33, 0.34, 0.35, 0.36, 0.37, 0.38, 0.39, 0.40, 0.41, 0.42,
    ],
    dtype=float,
)

# Precomputed with empyrical-compatible formulas (see portfolio_math_provenance.md).
REF_VAR_Q05 = -0.0455
REF_VAR_Q01 = -0.0702
REF_CVAR_Q05 = -0.06333333333333334
REF_VAR95_LOSS = 0.0455
REF_VAR99_LOSS = 0.0702
REF_ES95_LOSS = 0.06333333333333334
REF_MAX_DRAWDOWN = -0.19321893568000015
REF_CUMULATIVE_RETURN = 2142.6669627575257


class TestEmpyricalCompatibleQuantiles:
    def test_historical_var_quantile_matches_percentile(self):
        q05 = historical_var_quantile(REFERENCE_RETURNS, cutoff=0.05)
        q01 = historical_var_quantile(REFERENCE_RETURNS, cutoff=0.01)
        assert q05 == pytest.approx(REF_VAR_Q05, rel=1e-9)
        assert q01 == pytest.approx(REF_VAR_Q01, rel=1e-9)
        assert q05 == pytest.approx(float(np.percentile(REFERENCE_RETURNS, 5)), rel=1e-12)

    def test_conditional_var_quantile_matches_partition_mean(self):
        cvar = conditional_var_quantile(REFERENCE_RETURNS, cutoff=0.05)
        idx = int((REFERENCE_RETURNS.size - 1) * 0.05)
        expected = float(np.mean(np.partition(REFERENCE_RETURNS.copy(), idx)[: idx + 1]))
        assert cvar == pytest.approx(REF_CVAR_Q05, rel=1e-12)
        assert cvar == pytest.approx(expected, rel=1e-12)


class TestApexLossMagnitudes:
    def test_historical_var_es_positive_loss_convention(self):
        var95, var99, es95 = historical_var_es(REFERENCE_RETURNS)
        assert var95 == pytest.approx(REF_VAR95_LOSS, rel=1e-9)
        assert var99 == pytest.approx(REF_VAR99_LOSS, rel=1e-9)
        assert es95 == pytest.approx(REF_ES95_LOSS, rel=1e-9)
        assert var99 >= var95
        assert es95 >= var95

    def test_insufficient_observations_return_none(self):
        short = REFERENCE_RETURNS[:10]
        assert historical_var_es(short) == (None, None, None)
        assert historical_var_quantile(short) is None


class TestDrawdownAndReturns:
    def test_max_drawdown_reference(self):
        assert max_drawdown(REFERENCE_RETURNS) == pytest.approx(REF_MAX_DRAWDOWN, rel=1e-9)

    def test_cumulative_return_reference(self):
        assert cumulative_return(REFERENCE_RETURNS) == pytest.approx(REF_CUMULATIVE_RETURN, rel=1e-6)

    def test_simple_returns_from_prices(self):
        prices = [100.0, 110.0, 121.0]
        assert list(simple_returns(prices)) == pytest.approx([0.1, 0.1], rel=1e-9)


class TestRegression:
    def test_ols_alpha_beta_known_solution(self):
        bench = REFERENCE_RETURNS * 0.8 + 0.001
        alpha, beta, r2 = ols_alpha_beta(REFERENCE_RETURNS, bench)
        assert alpha == pytest.approx(-0.00125, abs=1e-9)
        assert beta == pytest.approx(1.25, rel=1e-9)
        assert r2 == pytest.approx(1.0, rel=1e-9)

    def test_multi_factor_betas(self):
        factors = {
            "mkt": REFERENCE_RETURNS * 0.9,
            "size": REFERENCE_RETURNS * 0.1 + 0.0005,
        }
        betas = multi_factor_betas(REFERENCE_RETURNS, factors)
        assert set(betas) == {"mkt", "size"}
        assert all(np.isfinite(v) for v in betas.values())


class TestZeroUpstreamDependency:
    def test_no_empyrical_or_pyfolio_imports(self):
        forbidden = {"empyrical", "pyfolio"}
        for mod in list(sys.modules):
            top = mod.split(".", 1)[0]
            assert top not in forbidden

    def test_portfolio_math_package_has_no_third_party_paths(self):
        pkg = importlib.import_module("app.services.risk.portfolio_math")
        for modinfo in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
            module = importlib.import_module(modinfo.name)
            source_path = getattr(module, "__file__", "") or ""
            assert "third_party" not in source_path.replace("\\", "/")
            assert "empyrical" not in source_path
            assert "pyfolio" not in source_path
