"""Freqtrade JSON signal bridge — keeps GPL code out of apex-intel repo."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_signal_path() -> Path:
    override = (os.getenv("FREQTRADE_SIGNAL_PATH") or "").strip()
    if override:
        return Path(override).resolve()
    root = os.getenv("APEX_INTEL_ROOT", "").strip()
    base = Path(root).resolve() if root else Path(__file__).resolve().parents[5]
    return base / "data" / "freqtrade_signal.json"


def write_signal_state(payload: dict[str, Any]) -> Path:
    """Write target portfolio state for external Freqtrade strategy to consume."""
    path = default_signal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        **payload,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
    }
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def read_signal_state() -> dict[str, Any] | None:
    path = default_signal_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
