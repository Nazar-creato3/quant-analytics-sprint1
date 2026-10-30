"""Volume profile, value area, cumulative delta (prompt 58B)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def volume_profile(trades: list[dict[str, Any]], *, tick: float = 1.0) -> dict[str, Any]:
    buckets: dict[float, float] = defaultdict(float)
    buy: dict[float, float] = defaultdict(float)
    sell: dict[float, float] = defaultdict(float)
    for t in trades:
        price = float(t["price"])
        qty = float(t["qty"])
        level = round(price / tick) * tick
        buckets[level] += qty
        side = str(t.get("side") or t.get("direction") or "").lower()
        if side in {"buy", "b", "1"}:
            buy[level] += qty
        elif side in {"sell", "s", "2"}:
            sell[level] += qty
    if not buckets:
        return {"poc": None, "value_area": None, "levels": [], "delta": None}
    poc = max(buckets, key=lambda k: (buckets[k], -k))
    total = sum(buckets.values())
    target = 0.70 * total
    lo = hi = poc
    covered = buckets[poc]
    ordered = sorted(buckets)
    while covered < target - 1e-12:
        i_lo = ordered.index(lo) if lo in ordered else 0
        i_hi = ordered.index(hi) if hi in ordered else len(ordered) - 1
        next_lo = ordered[i_lo - 1] if i_lo > 0 else None
        next_hi = ordered[i_hi + 1] if i_hi + 1 < len(ordered) else None
        if next_lo is None and next_hi is None:
            break
        vol_lo = buckets.get(next_lo, 0.0) if next_lo is not None else -1.0
        vol_hi = buckets.get(next_hi, 0.0) if next_hi is not None else -1.0
        if vol_hi > vol_lo:
            hi = next_hi
            covered += vol_hi
        elif vol_lo > vol_hi:
            lo = next_lo
            covered += vol_lo
        else:
            if next_hi is not None:
                hi = next_hi
                covered += vol_hi
            else:
                lo = next_lo
                covered += vol_lo
    delta = 0.0
    path: list[float] = []
    for t in trades:
        side = str(t.get("side") or t.get("direction") or "").lower()
        q = float(t["qty"])
        if side in {"buy", "b", "1"}:
            delta += q
        elif side in {"sell", "s", "2"}:
            delta -= q
        path.append(delta)
    levels = [{"price": p, "volume": buckets[p], "buy": buy[p], "sell": sell[p]} for p in sorted(buckets)]
    return {
        "poc": poc,
        "value_area": {"low": lo, "high": hi, "share": covered / total if total else None},
        "levels": levels,
        "delta": delta,
        "delta_path": path,
        "total_volume": total,
    }
