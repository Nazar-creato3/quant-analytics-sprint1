"""Internal accuracy summary vs naive last-direction (Prompt 11A)."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from app.services.forecast_log.store import get_store


def _wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    spread = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return ((centre - spread) / denom, (centre + spread) / denom)


def internal_summary() -> dict[str, Any]:
    store = get_store()
    latest: dict[int, bool] = {}
    for s in store.settlements():
        latest[s.log_id] = s.direction_correct
    by_h: dict[int, list[bool]] = defaultdict(list)
    rows = {r.id: r for r in store.rows()}
    for log_id, ok in latest.items():
        row = rows.get(log_id)
        if row is None:
            continue
        by_h[row.horizon_days].append(ok)
    horizons: list[dict[str, Any]] = []
    for h, hits in sorted(by_h.items()):
        n = len(hits)
        wins = sum(1 for x in hits if x)
        acc = wins / n if n else 0.0
        lo, hi = _wilson(wins, n)
        naive = 0.5
        horizons.append(
            {
                "horizon_days": h,
                "n": n,
                "hits": wins,
                "accuracy": acc,
                "ci_low": lo,
                "ci_high": hi,
                "naive_accuracy": naive,
                "beats_naive": acc > naive,
            }
        )
    return {
        "emissions": len(store.rows()),
        "settlements": len(store.settlements()),
        "horizons": horizons,
        "snapshots": store.snapshots(),
        "public": False,
    }
