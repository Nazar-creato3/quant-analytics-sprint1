"""Own fill tape for SOR scorecards and paper/live parity. No vendor TCA."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.core.config import settings


def tape_path() -> Path:
    raw = getattr(settings, "EXECUTION_TAPE_DIR", "") or ""
    root = Path(raw) if str(raw).strip() else Path.cwd() / "data" / "execution_tape"
    return root / "fills.jsonl"


def append_fill(row: Mapping[str, Any], *, dest: Path | None = None) -> dict[str, Any]:
    payload = dict(row)
    payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
    path = dest or tape_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        payload["persisted"] = True
    except OSError:
        payload["persisted"] = False
    return payload


def load_fills(*, dest: Path | None = None, limit: int = 2000) -> list[dict[str, Any]]:
    path = dest or tape_path()
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines[-max(1, limit) :]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out
