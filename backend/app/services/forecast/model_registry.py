"""File aliases live/shadow. Overlay keeps using the live pkl unless canary > 0."""

from __future__ import annotations

import json
from hashlib import sha1
from pathlib import Path
from typing import Any

from app.services.ml.model import MODEL_DIR


def _path() -> Path:
    return MODEL_DIR / "forecast_registry.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"aliases": {}, "canary_pct": 0, "history": []}


def _save(state: dict[str, Any]) -> None:
    try:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def set_alias(alias: str, model_name: str, *, ece: float | None = None, cv: float | None = None) -> None:
    state = _load()
    aliases = dict(state.get("aliases") or {})
    aliases[alias] = {
        "model_name": model_name,
        "ece": ece,
        "cv": cv,
    }
    state["aliases"] = aliases
    hist = list(state.get("history") or [])
    hist.append({"alias": alias, "model_name": model_name, "ece": ece, "cv": cv})
    state["history"] = hist[-40:]
    _save(state)


def get_alias(alias: str) -> str | None:
    row = (_load().get("aliases") or {}).get(alias)
    if not row:
        return None
    return str(row.get("model_name") or "") or None


def canary_pct() -> int:
    try:
        return max(0, min(100, int(_load().get("canary_pct") or 0)))
    except (TypeError, ValueError):
        return 0


def is_canary_symbol(symbol: str) -> bool:
    """Deterministic 0–99 bucket. Default canary_pct=0 → nobody."""
    pct = canary_pct()
    if pct <= 0:
        return False
    digest = sha1(symbol.strip().upper().encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100 < pct


def maybe_promote_shadow(*, new_ece: float, old_ece: float | None, new_cv: float, model_name: str) -> bool:
    """Promote shadow → live only if ECE improved or old ECE missing. Never on worse ECE."""
    if old_ece is not None and float(new_ece) > float(old_ece) + 0.01:
        return False
    set_alias("live", model_name, ece=new_ece, cv=new_cv)
    return True
