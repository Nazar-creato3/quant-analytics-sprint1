"""Compare old vs new calculation and persist diffs (file + optional callback)."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLD = 1e-9


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compare_values(old: Any, new: Any) -> dict[str, Any]:
    fo, fn = _as_float(old), _as_float(new)
    if fo is None or fn is None:
        match = old == new
        return {"old": old, "new": new, "delta": None, "match": match}
    delta = fn - fo
    return {"old": fo, "new": fn, "delta": delta, "match": abs(delta) <= DEFAULT_THRESHOLD}


def record_diff(
    name: str,
    payload_in: Any,
    old: Any,
    new: Any,
    *,
    path: Path,
    alert_threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    cmp = compare_values(old, new)
    row = {
        "name": name,
        "input": payload_in,
        "old": cmp["old"],
        "new": cmp["new"],
        "delta": cmp["delta"],
        "match": cmp["match"],
        "ts": time.time(),
        "alert": cmp["delta"] is not None and abs(float(cmp["delta"])) > alert_threshold,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    return row


def shadow_call(
    name: str,
    payload_in: Any,
    old_fn: Callable[..., Any],
    new_fn: Callable[..., Any],
    *,
    path: Path,
) -> Any:
    old = old_fn(payload_in)
    new = new_fn(payload_in)
    record_diff(name, payload_in, old, new, path=path)
    return old


def export_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"count": 0, "alerts": 0, "rows": []}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    alerts = sum(1 for r in rows if r.get("alert"))
    return {"count": len(rows), "alerts": alerts, "rows": rows}
