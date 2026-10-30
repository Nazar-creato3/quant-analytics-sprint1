"""Combinatorial purged CV + embargo + nested model selection.

Inner CPCV picks hyperparameters. Outer CPCV scores the *selected* config.
Never use the outer test path for selection — that was the simple purged-fold leak.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

from app.services.forecast.purged_cv import (
    PurgedFold,
    combinatorial_purged_splits,
    purged_kfold_splits,
)

FitPredict = Callable[[np.ndarray, np.ndarray, np.ndarray, dict], np.ndarray]


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    params: dict


@dataclass(frozen=True, slots=True)
class NestedSelection:
    winner: Candidate
    outer_accuracy: float
    outer_n: int
    inner_scores: tuple[tuple[str, float], ...]
    n_outer_folds: int
    method: str
    label_horizon: int
    embargo_pct: float


def _splits(
    n: int,
    *,
    label_horizon: int,
    embargo_pct: float,
    n_groups: int = 6,
    n_test_groups: int = 2,
) -> list[PurgedFold]:
    folds = combinatorial_purged_splits(
        n,
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        label_horizon=label_horizon,
        embargo_pct=embargo_pct,
    )
    if folds:
        return folds
    return purged_kfold_splits(
        n, n_splits=5, label_horizon=label_horizon, embargo_pct=embargo_pct
    )


def _accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, int]:
    mask = (y_true != 0) & (y_pred != 0)
    n = int(mask.sum())
    if n == 0:
        # Binary 0/1 meta-labels: zeros are valid class.
        if set(np.unique(y_true).tolist()) <= {0, 1} and set(np.unique(y_pred).tolist()) <= {0, 1}:
            n = int(y_true.size)
            if n == 0:
                return 0.5, 0
            hits = int((y_true == y_pred).sum())
            return hits / n, n
        return 0.5, 0
    hits = int((y_true[mask] == y_pred[mask]).sum())
    return hits / n, n


def score_config(
    X: np.ndarray,
    y: np.ndarray,
    candidate: Candidate,
    fit_predict: FitPredict,
    folds: Sequence[PurgedFold],
) -> tuple[float, int]:
    accs: list[float] = []
    ns: list[int] = []
    for fold in folds:
        tr, te = list(fold.train_indices), list(fold.test_indices)
        if len(tr) < 8 or len(te) < 3:
            continue
        pred = np.asarray(fit_predict(X[tr], y[tr], X[te], candidate.params))
        acc, n = _accuracy(y[te], pred)
        if n:
            accs.append(acc)
            ns.append(n)
    if not ns:
        return 0.5, 0
    w = np.array(ns, dtype=float)
    return float(np.average(accs, weights=w)), int(sum(ns))


def nested_cpcv_select(
    X: np.ndarray,
    y: np.ndarray,
    candidates: Sequence[Candidate],
    fit_predict: FitPredict,
    *,
    label_horizon: int,
    embargo_pct: float = 0.01,
    n_groups: int = 6,
    n_test_groups: int = 2,
) -> NestedSelection:
    """Select among candidates with nested combinatorial purged CV."""
    n = int(min(X.shape[0], y.shape[0]))
    X = X[:n]
    y = y[:n]
    outer = _splits(
        n,
        label_horizon=label_horizon,
        embargo_pct=embargo_pct,
        n_groups=n_groups,
        n_test_groups=n_test_groups,
    )
    if not candidates:
        raise ValueError("nested CPCV needs at least one candidate")
    if not outer:
        # Honest tiny-sample path: score in-sample but flag method.
        inner_scores = []
        best = candidates[0]
        best_acc = -1.0
        for cand in candidates:
            pred = np.asarray(fit_predict(X, y, X, cand.params))
            acc, _n = _accuracy(y, pred)
            inner_scores.append((cand.name, acc))
            if acc > best_acc:
                best, best_acc = cand, acc
        return NestedSelection(
            winner=best,
            outer_accuracy=best_acc,
            outer_n=n,
            inner_scores=tuple(inner_scores),
            n_outer_folds=0,
            method="in_sample_fallback",
            label_horizon=label_horizon,
            embargo_pct=embargo_pct,
        )

    outer_hits: dict[str, list[float]] = {c.name: [] for c in candidates}
    outer_ns: dict[str, list[int]] = {c.name: [] for c in candidates}
    inner_mean: dict[str, list[float]] = {c.name: [] for c in candidates}

    for ofold in outer:
        tr = list(ofold.train_indices)
        te = list(ofold.test_indices)
        if len(tr) < 16 or len(te) < 3:
            continue
        inner = _splits(
            len(tr),
            label_horizon=label_horizon,
            embargo_pct=embargo_pct,
            n_groups=max(4, min(n_groups, 5)),
            n_test_groups=1,
        )
        # Remap inner indices (relative to train subset) back is already 0..len(tr).
        inner_on_train = []
        for inf in inner:
            inner_on_train.append(
                PurgedFold(
                    train_indices=tuple(tr[i] for i in inf.train_indices if i < len(tr)),
                    test_indices=tuple(tr[i] for i in inf.test_indices if i < len(tr)),
                )
            )
        winner_inner = candidates[0]
        winner_acc = -1.0
        for cand in candidates:
            acc, _n = score_config(X, y, cand, fit_predict, inner_on_train)
            inner_mean[cand.name].append(acc)
            if acc > winner_acc:
                winner_inner, winner_acc = cand, acc
        # Outer evaluation of the *inner winner only* — other configs stay unused on te.
        pred = np.asarray(fit_predict(X[tr], y[tr], X[te], winner_inner.params))
        acc_o, n_o = _accuracy(y[te], pred)
        if n_o:
            outer_hits[winner_inner.name].append(acc_o)
            outer_ns[winner_inner.name].append(n_o)

    # Pick the config that won the most inner selections, tie-break on outer acc.
    scored: list[tuple[Candidate, float, int]] = []
    for cand in candidates:
        ns = outer_ns.get(cand.name) or []
        accs = outer_hits.get(cand.name) or []
        if ns:
            acc = float(np.average(accs, weights=np.array(ns, dtype=float)))
            scored.append((cand, acc, int(sum(ns))))
        else:
            scored.append((cand, 0.5, 0))
    scored.sort(key=lambda t: (t[2] > 0, t[1]), reverse=True)
    winner, outer_acc, outer_n = scored[0]
    inner_scores = tuple(
        (c.name, float(np.mean(inner_mean[c.name])) if inner_mean[c.name] else 0.5)
        for c in candidates
    )
    return NestedSelection(
        winner=winner,
        outer_accuracy=outer_acc,
        outer_n=outer_n,
        inner_scores=inner_scores,
        n_outer_folds=len(outer),
        method="nested_combinatorial_purged_cv",
        label_horizon=label_horizon,
        embargo_pct=embargo_pct,
    )


def default_lgbm_candidates() -> tuple[Candidate, ...]:
    return (
        Candidate("shallow", {"n_estimators": 120, "num_leaves": 12, "max_depth": 3}),
        Candidate("mid", {"n_estimators": 200, "num_leaves": 24, "max_depth": 5}),
        Candidate("deep", {"n_estimators": 280, "num_leaves": 31, "max_depth": 6}),
    )
