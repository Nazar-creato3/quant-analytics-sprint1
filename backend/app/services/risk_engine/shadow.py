"""Shadow-compare legacy VaR paths against the unified engine."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.services.qa.shadow_mode import record_diff
from app.services.risk.portfolio_math.var import historical_var_es
from app.services.risk_engine.fhs import fhs_bundle, historical_bundle

DIFF_PATH = Path(__file__).resolve().parents[3] / "data" / "risk_shadow" / "compare.jsonl"
_CACHE: list[dict] = []


def shadow_compare(returns: Sequence[float], *, user_id: str | None = None) -> dict:
    values = [float(x) for x in returns]
    old95, old99, old_es = historical_var_es(values, min_observations=2)
    new = fhs_bundle(values)
    hist = historical_bundle(values)
    row = record_diff(
        "var_95",
        {"n": len(values)},
        old95,
        new["var_95"],
        path=DIFF_PATH,
        alert_threshold=0.05,
    )
    _CACHE.append(
        {
            "old_var_95": old95,
            "old_var_99": old99,
            "old_es_95": old_es,
            "new": new,
            "hist_control": hist,
            "delta_var_95": row.get("delta"),
            "user_id": user_id,
        }
    )
    return _CACHE[-1]


def diffs(*, user_id: str | None = None) -> list[dict]:
    rows = list(_CACHE)
    if user_id is None:
        return rows
    return [item for item in rows if item.get("user_id") == user_id]


def reset_diffs() -> None:
    _CACHE.clear()
