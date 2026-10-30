"""Compare platform vs broker returns. Tolerance 0.1 percentage points."""
from __future__ import annotations

from decimal import Decimal


def compare(platform: dict, broker: dict, *, tol_pp: Decimal = Decimal("0.1")) -> dict:
    gaps = {}
    for key in ("twr", "mwr"):
        if key not in platform or key not in broker:
            continue
        gap = abs(Decimal(str(platform[key])) - Decimal(str(broker[key]))) * Decimal("100")
        gaps[key] = {"gap_pp": str(gap), "ok": gap <= tol_pp}
    return {"ok": all(v["ok"] for v in gaps.values()) if gaps else False, "gaps": gaps}
