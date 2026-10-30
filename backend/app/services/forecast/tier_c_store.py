"""Local PIT snapshots for C features. No network. Missing file = zeros."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.forecast.tier_c_schema import EMPTY_TIER_C_EXTRAS, TIER_C_FEATURE_COLUMNS


def _store_dir() -> Path:
    raw = getattr(settings, "TIER_C_STORE_DIR", "") or ""
    if raw.strip():
        return Path(raw)
    return Path("/app/data/tier_c")


def load_tier_c_extras(symbol: str) -> dict[str, float]:
    out = dict(EMPTY_TIER_C_EXTRAS)
    path = _store_dir() / f"{symbol.upper()}.json"
    if not path.is_file():
        return out
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, dict):
        return out
    filled = 0
    for key in TIER_C_FEATURE_COLUMNS:
        if key == "c_tier_present":
            continue
        if key not in features:
            continue
        try:
            val = float(features[key])
        except (TypeError, ValueError):
            continue
        out[key] = val
        if abs(val) > 1e-12:
            filled += 1
    if filled:
        out["c_tier_present"] = 1.0
    return out
