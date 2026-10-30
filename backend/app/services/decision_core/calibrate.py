"""Offline Beta(1,1) utility of a signal type. Live rank stays at 1 until founder review."""

from __future__ import annotations

from typing import Any

from app.services.decision_core.journal import entries_for, founder_reviewed
from app.services.qa.feature_flags import is_enabled

MIN_OBS = 30
_min_obs = MIN_OBS


def configure_min_obs(value: int) -> None:
    global _min_obs
    _min_obs = value


def reset_min_obs() -> None:
    configure_min_obs(MIN_OBS)


def observations(user_id: str) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for row in entries_for(user_id):
        action = row.get("action")
        if action not in {"opened", "noted", "dismissed"}:
            continue
        settled = any(
            (row.get("outcomes") or {}).get(key, {}).get("data_status") == "ok" for key in ("m1", "m3", "m6")
        )
        if not settled:
            continue
        bucket = counts.setdefault(row["signal_id"], {"success": 0, "failure": 0})
        if action in {"opened", "noted"}:
            bucket["success"] += 1
        else:
            bucket["failure"] += 1
    return counts


def proposed_weights(user_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for signal_id, bucket in observations(user_id).items():
        success = max(0, int(bucket.get("success") or 0))
        failure = max(0, int(bucket.get("failure") or 0))
        n = success + failure
        posterior = (1 + success) / (2 + n)
        weight = 1.0 if n < _min_obs else max(0.25, min(2.0, posterior / 0.5))
        out[signal_id] = {
            "n": n,
            "posterior": posterior,
            "weight": weight,
            "applied": False,
        }
    return out


def live_weights(user_id: str) -> dict[str, float]:
    if not is_enabled("qa_brain_weights_live") or not founder_reviewed():
        return {}
    return {
        signal_id: float(row["weight"])
        for signal_id, row in proposed_weights(user_id).items()
        if int(row["n"]) >= _min_obs
    }


def shadow_block(user_id: str) -> dict[str, Any] | None:
    if not is_enabled("qa_brain_weight_shadow"):
        return None
    return {
        "mode": "shadow",
        "min_obs": _min_obs,
        "weights": proposed_weights(user_id),
        "changes_rank": False,
    }
