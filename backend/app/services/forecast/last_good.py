"""Keep the previous LightGBM artifact if the new purged CV is worse."""

from __future__ import annotations

import json
from pathlib import Path


def should_replace_artifact(
    sidecar: Path,
    *,
    new_cv: float,
    new_n: int,
    min_n: int = 20,
    margin: float = 0.01,
) -> bool:
    if not sidecar.is_file():
        return True
    try:
        old = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    old_cv = float(old.get("cv") or 0.0)
    old_n = int(old.get("n") or 0)
    if old_n < min_n or new_n < min_n:
        return True
    return float(new_cv) + margin >= old_cv


def write_cv_sidecar(
    sidecar: Path,
    *,
    cv: float,
    n: int,
    extra: dict | None = None,
) -> None:
    payload = {"cv": float(cv), "n": int(n)}
    if extra:
        payload.update(extra)
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
