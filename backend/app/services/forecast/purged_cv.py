"""Purged K-Fold cross-validation with embargo (López de Prado).

Overlapping-horizon labels (e.g. 10-day forward returns with daily rollover)
leak information between train and test unless purged. This module excludes
training samples whose label window overlaps the test fold, plus an embargo gap.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import erfc, sqrt
from typing import Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class PurgedFold:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PurgedCVResult:
    accuracy: float
    n: int
    fold_accuracies: tuple[float, ...]
    fold_ns: tuple[int, ...]


def purged_kfold_splits(
    n_samples: int,
    *,
    n_splits: int = 5,
    label_horizon: int = 10,
    embargo_pct: float = 0.01,
) -> list[PurgedFold]:
    """Generate purged train/test index splits for time-series labels."""
    if n_samples < n_splits + label_horizon + 5:
        return []

    embargo = max(1, int(n_samples * embargo_pct))
    fold_size = n_samples // n_splits
    folds: list[PurgedFold] = []

    for fold in range(n_splits):
        test_start = fold * fold_size
        test_end = n_samples if fold == n_splits - 1 else (fold + 1) * fold_size
        test_indices = tuple(range(test_start, test_end))
        if not test_indices:
            continue

        purge_lo = max(0, test_start - label_horizon - embargo)
        purge_hi = min(n_samples, test_end + label_horizon + embargo)
        train_indices = tuple(
            i for i in range(n_samples) if i < purge_lo or i >= purge_hi
        )
        if len(train_indices) < 10 or len(test_indices) < 3:
            continue
        folds.append(PurgedFold(train_indices=train_indices, test_indices=test_indices))
    return folds


def evaluate_purged_accuracy(
    labels: Sequence[int],
    predictions: Sequence[int],
    *,
    n_splits: int = 5,
    label_horizon: int = 10,
    embargo_pct: float = 0.01,
) -> PurgedCVResult:
    """Compute mean accuracy across purged folds (labels/predictions aligned by index)."""
    n = min(len(labels), len(predictions))
    if n < 20:
        return PurgedCVResult(accuracy=0.5, n=0, fold_accuracies=(), fold_ns=())

    folds = purged_kfold_splits(
        n,
        n_splits=n_splits,
        label_horizon=label_horizon,
        embargo_pct=embargo_pct,
    )
    if not folds:
        hits = sum(1 for i in range(n) if labels[i] == predictions[i] and labels[i] != 0)
        total = sum(1 for i in range(n) if labels[i] != 0 and predictions[i] != 0)
        acc = hits / total if total else 0.5
        return PurgedCVResult(accuracy=acc, n=total, fold_accuracies=(acc,), fold_ns=(total,))

    fold_accs: list[float] = []
    fold_ns: list[int] = []
    for fold in folds:
        hits = total = 0
        for idx in fold.test_indices:
            if idx >= n:
                continue
            if labels[idx] == 0 or predictions[idx] == 0:
                continue
            total += 1
            if labels[idx] == predictions[idx]:
                hits += 1
        if total:
            fold_accs.append(hits / total)
            fold_ns.append(total)

    if not fold_accs:
        return PurgedCVResult(accuracy=0.5, n=0, fold_accuracies=(), fold_ns=())

    weights = np.array(fold_ns, dtype=float)
    weighted = float(np.average(fold_accs, weights=weights))
    return PurgedCVResult(
        accuracy=weighted,
        n=int(sum(fold_ns)),
        fold_accuracies=tuple(fold_accs),
        fold_ns=tuple(fold_ns),
    )


def combinatorial_purged_splits(
    n_samples: int,
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    label_horizon: int = 10,
    embargo_pct: float = 0.01,
) -> list[PurgedFold]:
    """Combinatorial purged CV (de Prado): every pair of groups is a test path."""
    if n_groups < 3 or n_test_groups < 1 or n_test_groups >= n_groups:
        return purged_kfold_splits(
            n_samples,
            n_splits=min(5, max(2, n_groups)),
            label_horizon=label_horizon,
            embargo_pct=embargo_pct,
        )
    if n_samples < n_groups * 8:
        return []

    embargo = max(1, int(n_samples * embargo_pct))
    group_size = n_samples // n_groups
    bounds = [
        (g * group_size, n_samples if g == n_groups - 1 else (g + 1) * group_size)
        for g in range(n_groups)
    ]
    folds: list[PurgedFold] = []
    for test_gs in combinations(range(n_groups), n_test_groups):
        test_indices: list[int] = []
        purge: set[int] = set()
        for g in test_gs:
            start, end = bounds[g]
            test_indices.extend(range(start, end))
            purge.update(
                range(max(0, start - label_horizon - embargo), min(n_samples, end + embargo))
            )
        train_indices = tuple(i for i in range(n_samples) if i not in purge)
        test_t = tuple(test_indices)
        if len(train_indices) < 10 or len(test_t) < 3:
            continue
        folds.append(PurgedFold(train_indices=train_indices, test_indices=test_t))
    return folds


def evaluate_cpcv_accuracy(
    labels: Sequence[int],
    predictions: Sequence[int],
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    label_horizon: int = 10,
    embargo_pct: float = 0.01,
) -> PurgedCVResult:
    """Accuracy across combinatorial purged paths (already-aligned labels/preds)."""
    n = min(len(labels), len(predictions))
    if n < 40:
        return evaluate_purged_accuracy(
            labels,
            predictions,
            n_splits=5,
            label_horizon=label_horizon,
            embargo_pct=embargo_pct,
        )
    folds = combinatorial_purged_splits(
        n,
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        label_horizon=label_horizon,
        embargo_pct=embargo_pct,
    )
    if not folds:
        return evaluate_purged_accuracy(
            labels, predictions, label_horizon=label_horizon, embargo_pct=embargo_pct
        )

    fold_accs: list[float] = []
    fold_ns: list[int] = []
    for fold in folds:
        hits = total = 0
        for idx in fold.test_indices:
            if idx >= n or labels[idx] == 0 or predictions[idx] == 0:
                continue
            total += 1
            if labels[idx] == predictions[idx]:
                hits += 1
        if total:
            fold_accs.append(hits / total)
            fold_ns.append(total)
    if not fold_accs:
        return PurgedCVResult(accuracy=0.5, n=0, fold_accuracies=(), fold_ns=())
    weights = np.array(fold_ns, dtype=float)
    return PurgedCVResult(
        accuracy=float(np.average(fold_accs, weights=weights)),
        n=int(sum(fold_ns)),
        fold_accuracies=tuple(fold_accs),
        fold_ns=tuple(fold_ns),
    )


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    n_trials: int = 1,
) -> dict[str, float]:
    """Bailey–de Prado DSR vs SR=0. Honest empty if the series is too short."""
    arr = np.asarray([float(x) for x in returns], dtype=float)
    arr = arr[np.isfinite(arr)]
    n = int(arr.size)
    if n < 10:
        return {"n": 0, "sharpe": 0.0, "dsr": 0.0, "n_trials": float(n_trials)}
    mu = float(arr.mean())
    sd = float(arr.std(ddof=1))
    if sd <= 1e-12:
        return {"n": float(n), "sharpe": 0.0, "dsr": 0.0, "n_trials": float(n_trials)}
    sr = mu / sd * sqrt(252.0) if n >= 20 else mu / sd
    skew = float(((arr - mu) ** 3).mean() / (sd**3 + 1e-18))
    kurt = float(((arr - mu) ** 4).mean() / (sd**4 + 1e-18))
    trials = max(1, int(n_trials))
    sr0 = 0.0
    if trials > 1:
        # Expected max Sharpe under N(0,1) trials — conservative null, not a promise.
        sr0 = (1.0 - 0.57721566) * _norm_ppf(1.0 - 1.0 / trials)
        sr0 += 0.57721566 * _norm_ppf(1.0 - 1.0 / (trials * 2.718281828))
        sr0 = max(0.0, float(sr0))
    denom = sqrt(max(1e-12, 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * (sr**2)))
    z = ((sr - sr0) * sqrt(max(n - 1, 1))) / denom
    dsr = float(0.5 * erfc(-z / sqrt(2.0)))
    return {
        "n": float(n),
        "sharpe": round(float(sr), 6),
        "dsr": round(dsr, 6),
        "n_trials": float(trials),
        "sr0": round(sr0, 6),
    }


def _norm_ppf(p: float) -> float:
    """Acklam rational approximation of N(0,1) quantile. p in (0,1)."""
    p = min(1.0 - 1e-12, max(1e-12, float(p)))
    a = (
        -3.969683028665376e01,
        2.209460984213642e02,
        -2.759285104469687e02,
        1.383577509590705e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = sqrt(-2.0 * np.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p > phigh:
        q = sqrt(-2.0 * np.log(1.0 - p))
        return -(
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )
