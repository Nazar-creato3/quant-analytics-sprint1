"""Weights for the six construction methods. Solver: scipy.optimize (ADR 0015).

Formulas: docs/methodology/portfolio-construction.md.
"""
from __future__ import annotations

import numpy as np

from app.services.target_portfolio.covariance import stabilize
from app.services.target_portfolio.types import ForecastView


class ConstructionError(Exception):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _equal_raw(n: int) -> np.ndarray:
    share = 1.0 / n
    return np.full(n, share, dtype=float)


def _bounds(
    n: int,
    *,
    allow_shorts: bool,
    upper: np.ndarray,
) -> list[tuple[float, float]]:
    bounds: list[tuple[float, float]] = []
    for i in range(n):
        hi = float(upper[i])
        lo = -hi if allow_shorts else 0.0
        if hi < lo:
            raise ConstructionError("infeasible", "верхняя граница доли ниже нижней")
        bounds.append((lo, hi))
    return bounds


def _precheck(lower_sum: float, upper: np.ndarray, groups: list[tuple[np.ndarray, float]]) -> None:
    if float(upper.sum()) < 1.0 - 1e-8:
        raise ConstructionError(
            "infeasible",
            f"сумма верхних границ долей {float(upper.sum()):.4f} меньше 1",
        )
    if lower_sum > 1.0 + 1e-8:
        raise ConstructionError("infeasible", "сумма нижних границ долей больше 1")
    for _mask, cap in groups:
        if cap < 1.0 - 1e-12 and cap <= 0:
            raise ConstructionError("infeasible", "потолок группы не положителен")


def _group_rows(labels: list[str], cap: float | None) -> list[tuple[np.ndarray, float]]:
    if cap is None:
        return []
    names = sorted({item for item in labels if item})
    rows: list[tuple[np.ndarray, float]] = []
    for name in names:
        mask = np.array([1.0 if item == name else 0.0 for item in labels], dtype=float)
        rows.append((mask, float(cap)))
    if names and float(cap) * len(names) < 1.0 - 1e-8:
        raise ConstructionError(
            "infeasible",
            f"сумма потолков групп {float(cap) * len(names):.4f} меньше 1",
        )
    return rows


def _project(
    target: np.ndarray,
    *,
    upper: np.ndarray,
    allow_shorts: bool,
    groups: list[tuple[np.ndarray, float]],
    w0: np.ndarray,
    capital: float,
    budget: float | None,
) -> tuple[np.ndarray, str]:
    """Closest feasible weights to `target` (squared distance)."""
    n = int(target.shape[0])
    bounds = _bounds(n, allow_shorts=allow_shorts, upper=upper)
    lower_sum = sum(lo for lo, _hi in bounds)
    _precheck(lower_sum, upper, groups)

    def objective(w: np.ndarray) -> float:
        gap = w - target
        return float(gap @ gap)

    return _slsqp(
        objective,
        n=n,
        bounds=bounds,
        groups=groups,
        w0=w0,
        capital=capital,
        budget=budget,
        x0=np.clip(target, [lo for lo, _ in bounds], [hi for _, hi in bounds]),
    )


def _slsqp(
    objective,
    *,
    n: int,
    bounds: list[tuple[float, float]],
    groups: list[tuple[np.ndarray, float]],
    w0: np.ndarray,
    capital: float,
    budget: float | None,
    x0: np.ndarray,
) -> tuple[np.ndarray, str]:
    from scipy.optimize import minimize

    constraints: list[dict] = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
    for mask, cap in groups:
        constraints.append(
            {"type": "ineq", "fun": lambda w, mask=mask, cap=cap: float(cap - mask @ w)}
        )
    if budget is not None and capital > 0:
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda w, w0=w0, capital=capital, budget=budget: _budget_slack(
                    w, w0, capital, budget
                ),
            }
        )
    start = _feasible_start(x0, bounds)
    result = minimize(
        objective,
        start,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-12, "maxiter": 400, "disp": False, "eps": 1e-8},
    )
    if not result.success or not np.isfinite(result.x).all():
        raise ConstructionError("infeasible", f"ограничения несовместны: {result.message}")
    weights = np.asarray(result.x, dtype=float)
    if abs(float(weights.sum()) - 1.0) > 1e-5:
        raise ConstructionError("infeasible", "решатель не собрал вес 1")
    for i, (lo, hi) in enumerate(bounds):
        if weights[i] < lo - 1e-5 or weights[i] > hi + 1e-5:
            raise ConstructionError("infeasible", "решатель вышел за границу доли")
    for mask, cap in groups:
        if float(mask @ weights) > cap + 1e-5:
            raise ConstructionError("infeasible", "решатель вышел за потолок группы")
    return weights, "scipy.optimize.SLSQP"


def _budget_slack(w: np.ndarray, w0: np.ndarray, capital: float, budget: float) -> float:
    dw = w - w0
    traded = float(capital) * (float(np.maximum(dw, 0).sum()) + float(np.maximum(-dw, 0).sum()))
    return float(budget) - traded


def _feasible_start(x0: np.ndarray, bounds: list[tuple[float, float]]) -> np.ndarray:
    lo = np.array([item[0] for item in bounds], dtype=float)
    hi = np.array([item[1] for item in bounds], dtype=float)
    w = np.clip(np.asarray(x0, dtype=float), lo, hi)
    if float(w.sum()) <= 0:
        w = np.clip(np.full(w.shape[0], 1.0 / w.shape[0]), lo, hi)
    for _ in range(w.shape[0] + 2):
        w = np.clip(w, lo, hi)
        total = float(w.sum())
        if total <= 0:
            break
        w = w / total
    return np.clip(w, lo, hi)


def solve_equal(
    n: int,
    *,
    upper: np.ndarray,
    allow_shorts: bool,
    groups: list[tuple[np.ndarray, float]],
    w0: np.ndarray,
    capital: float,
    budget: float | None,
) -> tuple[np.ndarray, str]:
    raw = _equal_raw(n)
    if groups or budget is not None or np.any(raw > upper + 1e-12) or allow_shorts:
        if not groups and budget is None and not allow_shorts and np.all(raw <= upper + 1e-12):
            return raw, "closed_form"
        return _project(
            raw,
            upper=upper,
            allow_shorts=allow_shorts,
            groups=groups,
            w0=w0,
            capital=capital,
            budget=budget,
        )
    return raw, "closed_form"


def solve_erc(
    cov: np.ndarray,
    *,
    upper: np.ndarray,
    allow_shorts: bool,
    groups: list[tuple[np.ndarray, float]],
    w0: np.ndarray,
    capital: float,
    budget: float | None,
) -> tuple[np.ndarray, str]:
    """Equal risk contribution. Maillard, Roncalli, Teïletche (2010)."""
    sigma, _note = stabilize(cov)
    n = sigma.shape[0]

    def objective(w: np.ndarray) -> float:
        marginal = sigma @ w
        rc = w * marginal
        return float(np.sum((rc - rc.mean()) ** 2))

    bounds = _bounds(n, allow_shorts=allow_shorts, upper=upper)
    _precheck(sum(lo for lo, _ in bounds), upper, groups)
    return _slsqp(
        objective,
        n=n,
        bounds=bounds,
        groups=groups,
        w0=w0,
        capital=capital,
        budget=budget,
        x0=_equal_raw(n),
    )


def _cluster_var(cov: np.ndarray, indices: tuple[int, ...]) -> float:
    sub = cov[np.ix_(indices, indices)]
    iv = 1.0 / np.clip(np.diag(sub), 1e-18, None)
    weights = iv / iv.sum()
    return float(weights @ sub @ weights)


def _linkage(corr: np.ndarray) -> list:
    """Deterministic single-linkage tree. Tie-break: smaller index first."""
    n = corr.shape[0]
    dist = np.sqrt(np.clip((1.0 - corr) * 0.5, 0.0, None))
    nodes: list[dict] = [{"idx": (i,), "left": None, "right": None} for i in range(n)]
    active = list(range(n))

    def pair_dist(a: tuple[int, ...], b: tuple[int, ...]) -> float:
        best = np.inf
        for i in a:
            for j in b:
                best = min(best, float(dist[i, j]))
        return best

    while len(active) > 1:
        best_key = None
        pair = (0, 1)
        for p in range(len(active)):
            for q in range(p + 1, len(active)):
                left = nodes[active[p]]["idx"]
                right = nodes[active[q]]["idx"]
                key = (pair_dist(left, right), left[0], right[0])
                if best_key is None or key < best_key:
                    best_key = key
                    pair = (p, q)
        p, q = pair
        i, j = active[p], active[q]
        left_node, right_node = nodes[i], nodes[j]
        if left_node["idx"][0] > right_node["idx"][0]:
            left_node, right_node = right_node, left_node
        merged = {
            "idx": left_node["idx"] + right_node["idx"],
            "left": left_node,
            "right": right_node,
        }
        nodes.append(merged)
        new_id = len(nodes) - 1
        active = [a for k, a in enumerate(active) if k not in {p, q}]
        active.append(new_id)
    return nodes[active[0]]


def solve_hrp(cov: np.ndarray) -> np.ndarray:
    """HRP recursive bisection. López de Prado (2016), SSRN 2708678."""
    sigma, _note = stabilize(cov)
    n = sigma.shape[0]
    vol = np.sqrt(np.clip(np.diag(sigma), 1e-18, None))
    corr = sigma / np.outer(vol, vol)
    corr = np.clip(corr, -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)
    root = _linkage(corr)
    weights = np.zeros(n, dtype=float)

    def allocate(node: dict, budget: float) -> None:
        if node["left"] is None:
            weights[node["idx"][0]] = budget
            return
        left_var = _cluster_var(sigma, node["left"]["idx"])
        right_var = _cluster_var(sigma, node["right"]["idx"])
        total = left_var + right_var
        alpha = 0.5 if total <= 0 else 1.0 - left_var / total
        allocate(node["left"], budget * alpha)
        allocate(node["right"], budget * (1.0 - alpha))

    allocate(root, 1.0)
    if not np.isfinite(weights).all() or abs(float(weights.sum()) - 1.0) > 1e-6:
        raise ConstructionError("infeasible", "HRP не собрал вес 1")
    return weights


def solve_mean_variance(
    cov: np.ndarray,
    mu: np.ndarray,
    *,
    risk_aversion: float,
    upper: np.ndarray,
    allow_shorts: bool,
    groups: list[tuple[np.ndarray, float]],
    w0: np.ndarray,
    capital: float,
    budget: float | None,
) -> tuple[np.ndarray, str]:
    """Mean-variance. Markowitz (1952). Objective: μ'w - (λ/2) w'Σw, long the constraints."""
    sigma, _note = stabilize(cov)
    n = sigma.shape[0]
    lam = float(risk_aversion)

    def objective(w: np.ndarray) -> float:
        return float(0.5 * lam * (w @ sigma @ w) - mu @ w)

    bounds = _bounds(n, allow_shorts=allow_shorts, upper=upper)
    _precheck(sum(lo for lo, _ in bounds), upper, groups)
    return _slsqp(
        objective,
        n=n,
        bounds=bounds,
        groups=groups,
        w0=w0,
        capital=capital,
        budget=budget,
        x0=_equal_raw(n),
    )


def black_litterman_mu(
    cov: np.ndarray,
    w_eq: np.ndarray,
    views: list[ForecastView],
    tickers: list[str],
    *,
    tau: float,
    delta: float,
) -> np.ndarray:
    """Posterior mean. Black and Litterman (1992); He and Litterman (1999)."""
    if not views:
        raise ConstructionError("нет данных", "нет данных")
    sigma, _note = stabilize(cov)
    n = sigma.shape[0]
    index = {name: i for i, name in enumerate(tickers)}
    rows = []
    qs = []
    conf = []
    for view in views:
        if view.ticker not in index:
            continue
        row = np.zeros(n, dtype=float)
        row[index[view.ticker]] = 1.0
        rows.append(row)
        qs.append(float(view.q))
        conf.append(float(view.confidence))
    if not rows:
        raise ConstructionError("нет данных", "нет данных")
    matrix_p = np.vstack(rows)
    vector_q = np.asarray(qs, dtype=float)
    pi = float(delta) * (sigma @ np.asarray(w_eq, dtype=float))
    tau_sigma = float(tau) * sigma
    mid = matrix_p @ tau_sigma @ matrix_p.T
    omega = np.zeros((len(rows), len(rows)), dtype=float)
    for i, confidence in enumerate(conf):
        c = float(np.clip(confidence, 0.05, 0.95))
        omega[i, i] = ((1.0 - c) / c) * max(float(mid[i, i]), 1e-18)
    inv_tau = np.linalg.pinv(tau_sigma)
    inv_omega = np.linalg.pinv(omega)
    precision = inv_tau + matrix_p.T @ inv_omega @ matrix_p
    rhs = inv_tau @ pi + matrix_p.T @ inv_omega @ vector_q
    mu = np.linalg.solve(precision, rhs)
    if not np.isfinite(mu).all():
        raise ConstructionError("нет данных", "нет данных")
    return mu


def solve_cvar(
    scenarios: np.ndarray,
    *,
    alpha: float,
    upper: np.ndarray,
    allow_shorts: bool,
    groups: list[tuple[np.ndarray, float]],
) -> tuple[np.ndarray, str]:
    """Rockafellar and Uryasev (2000), Journal of Risk. Loss = -scenario return."""
    from scipy.optimize import linprog

    panel = np.asarray(scenarios, dtype=float)
    if panel.ndim != 2 or panel.shape[0] < 2:
        raise ConstructionError("нет данных", "нет данных")
    n = panel.shape[1]
    s_count = panel.shape[0]
    if not (0.0 < alpha < 1.0):
        raise ConstructionError("infeasible", "уровень CVaR вне (0, 1)")
    bounds = _bounds(n, allow_shorts=allow_shorts, upper=upper)
    _precheck(sum(lo for lo, _ in bounds), upper, groups)
    # x = [w (n), zeta (1), u (S)]
    c = np.zeros(n + 1 + s_count, dtype=float)
    c[n] = 1.0
    c[n + 1 :] = 1.0 / ((1.0 - alpha) * s_count)
    # -r·w - zeta - u <= 0
    a_ub = []
    b_ub = []
    for s in range(s_count):
        row = np.zeros(n + 1 + s_count, dtype=float)
        row[:n] = -panel[s]
        row[n] = -1.0
        row[n + 1 + s] = -1.0
        a_ub.append(row)
        b_ub.append(0.0)
    for mask, cap in groups:
        row = np.zeros(n + 1 + s_count, dtype=float)
        row[:n] = mask
        a_ub.append(row)
        b_ub.append(cap)
    a_eq = np.zeros((1, n + 1 + s_count), dtype=float)
    a_eq[0, :n] = 1.0
    var_bounds: list[tuple[float | None, float | None]] = list(bounds)
    var_bounds.append((None, None))
    var_bounds.extend([(0.0, None)] * s_count)
    result = linprog(
        c,
        A_ub=np.vstack(a_ub) if a_ub else None,
        b_ub=np.asarray(b_ub, dtype=float) if b_ub else None,
        A_eq=a_eq,
        b_eq=np.array([1.0]),
        bounds=var_bounds,
        method="highs",
    )
    if not result.success or result.x is None or not np.isfinite(result.x[:n]).all():
        raise ConstructionError("infeasible", f"ограничения несовместны: {result.message}")
    weights = np.asarray(result.x[:n], dtype=float)
    if abs(float(weights.sum()) - 1.0) > 1e-5:
        raise ConstructionError("infeasible", "решатель CVaR не собрал вес 1")
    return weights, "scipy.optimize.linprog.highs"


def sample_mu(panel: np.ndarray) -> np.ndarray:
    return np.mean(panel, axis=0)


def prepare_upper(
    n: int,
    *,
    name_cap: float | None,
    liquidity_caps: np.ndarray | None,
    allow_shorts: bool,
) -> np.ndarray:
    hi = np.full(n, 1.0 if allow_shorts else 1.0, dtype=float)
    if name_cap is not None:
        hi = np.minimum(hi, float(name_cap))
    if liquidity_caps is not None:
        hi = np.minimum(hi, liquidity_caps)
    if np.any(hi <= 0):
        raise ConstructionError("infeasible", "верхняя граница доли не положительна")
    return hi
