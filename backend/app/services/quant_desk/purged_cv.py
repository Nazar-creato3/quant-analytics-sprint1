"""Purged walk-forward + embargo (ESL / AFML). Do not use random k-fold on bars."""
from __future__ import annotations


def embargo_index(event_end: int, embargo: int, n: int) -> int:
    return min(n, max(0, event_end + max(0, embargo)))


def purged_walk_forward(
    n: int,
    *,
    n_splits: int = 4,
    embargo: int = 5,
    min_train: int = 40,
) -> list[tuple[list[int], list[int]]]:
    """Return (train_idx, test_idx) folds. Test blocks move forward; train drops embargo overlap."""
    if n < min_train + embargo + 8 or n_splits < 2:
        return []
    fold = max(8, n // (n_splits + 1))
    out: list[tuple[list[int], list[int]]] = []
    for k in range(n_splits):
        test_start = min_train + k * fold
        test_end = min(n, test_start + fold)
        if test_end - test_start < 5:
            continue
        purge_from = max(0, test_start - embargo)
        train = list(range(0, purge_from))
        after = embargo_index(test_end, embargo, n)
        if after < n:
            train.extend(range(after, n))
            # Walk-forward: later bars after the test belong to the future — drop them.
            train = [i for i in train if i < test_start]
        if len(train) < min_train:
            continue
        out.append((train, list(range(test_start, test_end))))
    return out
