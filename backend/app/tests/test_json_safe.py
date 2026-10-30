"""JSON-safe sanitization for API payloads."""
from __future__ import annotations

import math

from app.utils.json_safe import coerce_finite_float, finite_float, sanitize_for_json


def test_coerce_finite_float_defaults():
    assert coerce_finite_float(float("nan"), 5.0) == 5.0
    assert coerce_finite_float(2.5, 5.0) == 2.5


def test_safe_json_response_renders_without_nan():
    from app.utils.safe_json_response import SafeJSONResponse

    body = SafeJSONResponse({"x": float("nan"), "y": [1.0, float("inf")]}).body.decode()
    assert "NaN" not in body
    assert "null" in body


def test_sanitize_for_json_replaces_nan_and_inf():
    import numpy as np

    assert finite_float(np.nan) is None
    assert finite_float(1.5) == 1.5
    payload = {
        "a": float("nan"),
        "b": float("inf"),
        "c": [1.0, float("-inf")],
        "d": {"x": math.nan},
    }
    out = sanitize_for_json(payload)
    assert out == {"a": None, "b": None, "c": [1.0, None], "d": {"x": None}}


def test_coerce_finite_float_defaults():
    from app.utils.json_safe import coerce_finite_float

    assert coerce_finite_float(float("nan")) == 0.0
    assert coerce_finite_float(2.5) == 2.5
    assert coerce_finite_float(None, default=-1.0) == -1.0


def test_safe_json_response_renders_without_nan():
    from app.utils.safe_json_response import SafeJSONResponse

    body = SafeJSONResponse({"x": float("nan"), "y": [float("inf")]}).body
    assert b"NaN" not in body
    assert b"null" in body
