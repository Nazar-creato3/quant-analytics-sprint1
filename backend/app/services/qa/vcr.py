"""Minimal VCR: record/replay JSON HTTP payloads with secret redaction."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SECRET_KEYS = re.compile(r"(token|secret|password|authorization|api[_-]?key|cookie)", re.I)


def cassette_path(root: Path, vendor: str, name: str) -> Path:
    return root / vendor / f"{name}.json"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _SECRET_KEYS.search(str(k)):
                out[k] = "***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str) and _SECRET_KEYS.search(value) and len(value) > 12:
        return "***"
    return value


def save_cassette(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(payload), indent=2) + "\n", encoding="utf-8")


def load_cassette(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
