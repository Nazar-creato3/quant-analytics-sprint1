"""Disable weak score blocks after repeated losing closes. Local JSON, no vendor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from app.services.ml.model import MODEL_DIR

_KILL_AFTER = 12


def _path() -> Path:
    return MODEL_DIR / "forecast_feature_kill.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"losses": {}, "killed": []}


def _save(payload: dict[str, Any]) -> None:
    try:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        return


def killed_blocks() -> set[str]:
    return {str(x) for x in (_load().get("killed") or [])}


def record_losing_blocks(blocks: Iterable[str], *, pnl: float) -> set[str]:
    if float(pnl) >= 0:
        return killed_blocks()
    state = _load()
    losses: dict[str, int] = dict(state.get("losses") or {})
    killed = set(state.get("killed") or [])
    for raw in blocks:
        name = str(raw or "").strip().lower()
        if not name:
            continue
        losses[name] = int(losses.get(name) or 0) + 1
        if losses[name] >= _KILL_AFTER:
            killed.add(name)
    state["losses"] = losses
    state["killed"] = sorted(killed)
    _save(state)
    return killed


def blocks_from_maneuver_meta(meta: dict[str, Any] | None) -> list[str]:
    overlay = (meta or {}).get("forecast_overlay") or {}
    out: list[str] = []
    if overlay.get("p_calibrated") is not None:
        out.append("score")
    if overlay.get("p_beat_20") is not None:
        out.append("technical")
    return out
