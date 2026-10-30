"""Shared calc outcome: never invent a number when inputs are missing (E-4-6)."""
from __future__ import annotations

from typing import Any, Literal

DataStatus = Literal["ok", "нет данных", "недостаточно данных"]


def no_data(*, reason: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "data_status": "нет данных",
        "status": "insufficient_data",
        "reason": reason,
        "incomplete": True,
    }
    out.update(extra)
    return out


def insufficient(*, reason: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "data_status": "недостаточно данных",
        "status": "insufficient_data",
        "reason": reason,
        "incomplete": True,
    }
    out.update(extra)
    return out


def ok(**extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"data_status": "ok", "status": "ok", "incomplete": False}
    out.update(extra)
    return out


def assert_no_numeric_when_empty(payload: dict[str, Any], keys: tuple[str, ...]) -> None:
    """Contract helper for tests: missing-data payloads must not carry fake numbers."""
    status = payload.get("data_status")
    if status not in {"нет данных", "недостаточно данных"}:
        raise AssertionError(f"expected empty-data status, got {status!r}")
    for key in keys:
        if key not in payload:
            continue
        val = payload[key]
        if isinstance(val, bool):
            continue
        if isinstance(val, (int, float)) and val == 0:
            raise AssertionError(f"{key}={val!r} looks like a numeric substitution")
        if val == "0" or val == "0E-27":
            raise AssertionError(f"{key}={val!r} looks like a numeric substitution")
