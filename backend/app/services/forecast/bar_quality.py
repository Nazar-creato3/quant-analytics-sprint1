"""Cheap bar sanity. Does not call vendors."""

from __future__ import annotations

from typing import Sequence


def last_bar_sane(closes: Sequence[float], *, max_abs_return: float = 0.35) -> bool:
    if len(closes) < 2:
        return False
    prev, last = float(closes[-2]), float(closes[-1])
    if prev <= 0 or last <= 0:
        return False
    return abs(last / prev - 1.0) < max_abs_return


def bars_dq(
    closes: Sequence[float],
    volumes: Sequence[float] | None = None,
    *,
    max_abs_return: float = 0.35,
) -> dict[str, object]:
    """Skip forecast on a dirty last day. No vendor."""
    reasons: list[str] = []
    if len(closes) < 5:
        return {"ok": False, "reasons": ["too_short"]}
    if not last_bar_sane(closes, max_abs_return=max_abs_return):
        reasons.append("last_jump")
    zeros = sum(1 for c in closes[-20:] if float(c) <= 0)
    if zeros:
        reasons.append("non_positive_close")
    if volumes is not None and len(volumes) == len(closes):
        if float(volumes[-1] or 0) <= 0:
            reasons.append("zero_volume")
    return {"ok": len(reasons) == 0, "reasons": reasons}
