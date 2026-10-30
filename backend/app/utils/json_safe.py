"""Make Python values safe for standard JSON (no NaN/Inf)."""
from __future__ import annotations

import math
from numbers import Real
from typing import Any


def finite_float(value: Any) -> float | None:
    """Coerce numeric values to a JSON-safe float, or None if missing/non-finite."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Real):
        try:
            f = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return f if math.isfinite(f) else None
    return None


def coerce_finite_float(value: Any, default: float = 0.0) -> float:
    """Like ``finite_float`` but never returns None — use for DB exposure / sizing."""
    f = finite_float(value)
    return default if f is None else f


def sanitize_for_json(value: Any) -> Any:
    if isinstance(value, Real) and not isinstance(value, bool):
        f = finite_float(value)
        return f
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_json(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize_for_json(v) for v in value]
    return value
