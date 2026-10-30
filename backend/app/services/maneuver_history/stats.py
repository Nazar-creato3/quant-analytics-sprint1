"""Metrics and selection statistics for the maneuver history.

Sharpe, Sortino, volatility, and max drawdown are the terminal implementations.
ES is quant_math.expected_shortfall. Block length, the deflated Sharpe, and
CSCV are documented in docs/methodology/maneuver-history.md.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal
from itertools import combinations

import numpy as np
from scipy.stats import kurtosis, norm, skew

from app.services.quant_math.core import expected_shortfall, value_at_risk
from app.services.terminal_platform.quant.metrics import max_drawdown as wealth_drawdown
from app.services.terminal_platform.quant.metrics import sharpe_ratio, sortino_ratio
from app.services.terminal_platform.quant.metrics import volatility as return_volatility

N_BOOT = 200
PPY = 252
_EIGHT = Decimal("0.00000001")
_EULER = 0.5772156649015329


def _text(value: float) -> str:
    return format(Decimal(str(value)).quantize(_EIGHT, rounding=ROUND_HALF_EVEN), "f")


def period_sharpe(values: np.ndarray) -> float | None:
    if len(values) < 2:
        return None
    std = float(values.std(ddof=1))
    if std <= 1e-15:
        return None
    return float(values.mean() / std)


def _stat(values: np.ndarray, kind: str) -> float:
    if kind == "mean":
        return float(values.mean())
    if kind == "sharpe":
        return float(sharpe_ratio(values.tolist(), 0.0, periods_per_year=PPY))
    if kind == "drawdown":
        wealth = [1.0]
        for item in values:
            wealth.append(wealth[-1] * (1.0 + float(item)))
        return float(wealth_drawdown(wealth))
    raise ValueError(kind)


def block_bootstrap_interval(
    values: list[float],
    *,
    seed: int,
    kind: str,
    n_boot: int = N_BOOT,
) -> dict[str, str | int]:
    """Moving-block bootstrap percentile interval. Seed fixes the draws."""
    arr = np.asarray(values, dtype=float)
    if len(arr) < 2 or not np.isfinite(arr).all():
        return {"status": "нет данных", "reason": "мало наблюдений"}
    block = max(1, int(round(len(arr) ** (1.0 / 3.0))))
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(len(arr) / block))
    draws = np.empty(n_boot, dtype=float)
    upper = len(arr) - block + 1
    for index in range(n_boot):
        if upper <= 1:
            starts = np.zeros(n_blocks, dtype=int)
        else:
            starts = rng.integers(0, upper, size=n_blocks)
        sample = np.concatenate([arr[start : start + block] for start in starts])[: len(arr)]
        draws[index] = _stat(sample, kind)
    point = _stat(arr, kind)
    low = float(np.quantile(draws, 0.025))
    high = float(np.quantile(draws, 0.975))
    return {
        "status": "ok",
        "kind": kind,
        "point": _text(point),
        "low": _text(low),
        "high": _text(high),
        "block": block,
        "draws": n_boot,
    }


def deflated_sharpe_ratio(returns: list[float], trial_sharpes: list[float]) -> dict[str, str | int]:
    """Bailey and López de Prado (2014) deflated Sharpe of `returns`.

    `trial_sharpes` are the non-annualized Sharpes of the tried parameters.
    The threshold uses their cross-sectional variance. N < 2 has no selection
    threshold. Cash tax and a risk-free rate are not part of this ratio.
    """
    arr = np.asarray(returns, dtype=float)
    selected = period_sharpe(arr)
    trials = [float(item) for item in trial_sharpes if item is not None and math.isfinite(float(item))]
    if selected is None or len(arr) < 4 or len(trials) < 1:
        return {"status": "нет данных", "reason": "мало наблюдений или нулевая дисперсия"}
    n_trials = len(trials)
    if n_trials >= 2:
        variance = float(np.var(np.asarray(trials, dtype=float), ddof=1))
    else:
        variance = 0.0
    if n_trials >= 2 and variance > 0:
        z1 = float(norm.ppf(1.0 - 1.0 / n_trials))
        z2 = float(norm.ppf(1.0 - math.exp(-1.0) / n_trials))
        sr_star = math.sqrt(variance) * ((1.0 - _EULER) * z1 + _EULER * z2)
    else:
        sr_star = 0.0
    sample_skew = float(skew(arr, bias=False))
    sample_kurt = float(kurtosis(arr, bias=False, fisher=False))
    inside = 1.0 - sample_skew * selected + ((sample_kurt - 1.0) / 4.0) * selected * selected
    if not math.isfinite(inside) or inside <= 0:
        return {"status": "нет данных", "reason": "знаменатель дефлированного Шарпа не положителен"}
    z_score = (selected - sr_star) * math.sqrt(len(arr) - 1) / math.sqrt(inside)
    probability = float(norm.cdf(z_score))
    return {
        "status": "ok",
        "dsr": _text(probability),
        "sr": _text(selected),
        "sr_star": _text(sr_star),
        "trials": n_trials,
    }


def cscv_probability(columns: list[list[float]]) -> dict[str, str | int]:
    """Probability of backtest overfitting, CSCV.

    Bailey, Borwein, López de Prado, and Zhu (2017), Journal of Computational
    Finance. Performance in a block is the non-annualized Sharpe. PBO is the
    share of splits whose logit of the out-of-sample rank is negative.
    Rank 1 is the worst. Relative rank is rank / (N + 1).
    """
    if len(columns) < 2:
        return {"status": "нет данных", "reason": "меньше двух параметров"}
    length = len(columns[0])
    if length < 8 or any(len(column) != length for column in columns):
        return {"status": "нет данных", "reason": "ряды разной длины или короче 8"}
    matrix = np.column_stack([np.asarray(column, dtype=float) for column in columns])
    if not np.isfinite(matrix).all():
        return {"status": "нет данных", "reason": "в ряде нет числа"}
    groups = 8 if length >= 16 else 4
    bounds = [int(round(index * length / groups)) for index in range(groups + 1)]
    if any(bounds[index] >= bounds[index + 1] for index in range(groups)):
        return {"status": "нет данных", "reason": "блоки CSCV пустые"}
    slices = [list(range(bounds[index], bounds[index + 1])) for index in range(groups)]
    width = matrix.shape[1]

    def _score(block: np.ndarray) -> float | None:
        sharpe = period_sharpe(block)
        if sharpe is not None:
            return sharpe
        if len(block) < 2 or not np.isfinite(block).all():
            return None
        return float(block.mean())

    negative = 0
    used = 0
    for comb in combinations(range(groups), groups // 2):
        train = [row for group in comb for row in slices[group]]
        test = [row for group in range(groups) if group not in comb for row in slices[group]]
        is_score = [_score(matrix[train, col]) for col in range(width)]
        oos_score = [_score(matrix[test, col]) for col in range(width)]
        if any(item is None for item in is_score) or any(item is None for item in oos_score):
            continue
        is_arr = np.asarray(is_score, dtype=float)
        oos_arr = np.asarray(oos_score, dtype=float)
        best = int(np.argmax(is_arr))
        order = np.argsort(oos_arr, kind="mergesort")
        rank = int(np.where(order == best)[0][0]) + 1
        omega = rank / (width + 1)
        logit = math.log(omega / (1.0 - omega))
        used += 1
        if logit < 0:
            negative += 1
    if used == 0:
        return {"status": "нет данных", "reason": "ни одно разбиение CSCV не посчиталось"}
    return {
        "status": "ok",
        "pbo": _text(negative / used),
        "splits": used,
        "groups": groups,
    }


def wealth_ratio(start: Decimal, end: Decimal) -> str:
    if start == 0:
        return "нет данных"
    ratio = ((end - start) / start).quantize(_EIGHT, rounding=ROUND_HALF_EVEN)
    return format(ratio, "f")


def summarize_metrics(
    *,
    wealth_before: list[Decimal],
    return_after: str,
    after_status: str,
    period_returns: list[float],
    trades: int,
    tax: dict[str, str | bool | None],
    turnover: Decimal,
    maneuver_hits: int,
    decisions: int,
    breach_days: int,
    priced_days: int,
    bootstrap_seed: int,
) -> dict[str, object]:
    """Point metrics plus block-bootstrap intervals. Risk-free rate is 0."""
    if len(wealth_before) < 2:
        blank = "нет данных"
        return {
            "return_before_costs": blank,
            "return_after_costs": blank,
            "return_after_costs_status": "нет данных",
            "volatility": blank,
            "max_drawdown": blank,
            "es_975": blank,
            "sharpe": blank,
            "sortino": blank,
            "turnover": format(turnover, "f"),
            "maneuver_frequency": blank,
            "limit_breach_share": blank,
            "trades": trades,
            "tax_base": tax.get("tax_base"),
            "tax_cash": None,
            "tax_cash_computed": False,
            "tax_cash_reason": tax.get("tax_cash_reason"),
            "bootstrap_mean": {"status": "нет данных"},
            "bootstrap_sharpe": {"status": "нет данных"},
            "risk_free": "0",
            "risk_free_reason": "безрисковый ряд не задан, избыток считается от нуля",
        }
    before = wealth_ratio(wealth_before[0], wealth_before[-1])
    after = return_after
    if len(period_returns) >= 2:
        vol = _text(float(return_volatility(period_returns, annualize=True, periods_per_year=PPY)))
        sharpe = _text(float(sharpe_ratio(period_returns, 0.0, periods_per_year=PPY)))
        sortino = _text(float(sortino_ratio(period_returns, 0.0, periods_per_year=PPY)))
        var = value_at_risk(period_returns, 0.975)
        es = _text(float(expected_shortfall(period_returns, 0.975, var)))
        boot_mean = block_bootstrap_interval(period_returns, seed=bootstrap_seed, kind="mean")
        boot_sharpe = block_bootstrap_interval(period_returns, seed=bootstrap_seed + 1, kind="sharpe")
    else:
        vol = sharpe = sortino = es = "нет данных"
        boot_mean = {"status": "нет данных"}
        boot_sharpe = {"status": "нет данных"}
    drawdown = _text(float(wealth_drawdown([float(item) for item in wealth_before])))
    if decisions > 0:
        frequency = format(
            (Decimal(maneuver_hits) / Decimal(decisions)).quantize(_EIGHT, rounding=ROUND_HALF_EVEN),
            "f",
        )
    else:
        frequency = "нет данных"
    if priced_days > 0:
        share = format(
            (Decimal(breach_days) / Decimal(priced_days)).quantize(_EIGHT, rounding=ROUND_HALF_EVEN),
            "f",
        )
    else:
        share = "нет данных"
    return {
        "return_before_costs": before,
        "return_after_costs": after,
        "return_after_costs_status": after_status,
        "volatility": vol,
        "max_drawdown": drawdown,
        "es_975": es,
        "sharpe": sharpe,
        "sortino": sortino,
        "turnover": format(turnover.quantize(_EIGHT, rounding=ROUND_HALF_EVEN), "f"),
        "maneuver_frequency": frequency,
        "limit_breach_share": share,
        "trades": trades,
        "tax_base": tax.get("tax_base"),
        "tax_cash": None,
        "tax_cash_computed": False,
        "tax_cash_reason": tax.get("tax_cash_reason"),
        "bootstrap_mean": boot_mean,
        "bootstrap_sharpe": boot_sharpe,
        "risk_free": "0",
        "risk_free_reason": "безрисковый ряд не задан, избыток считается от нуля",
    }
