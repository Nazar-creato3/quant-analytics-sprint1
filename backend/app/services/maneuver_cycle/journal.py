"""Append-only hash chain for maneuver events (Prompt 39).

The digest covers the previous hash and the canonical JSON of the event
without the hash field. Methodology: docs/methodology/maneuver-cycle.md
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

_EVENT_FIELDS = (
    "id",
    "user_id",
    "name",
    "payload",
    "model_version",
    "at",
    "prev_hash",
    "profile_snapshot",
    "model_versions",
    "shown_text",
)


def seal_event(body: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with hash set. `body` must already contain prev_hash."""
    canonical = {key: body.get(key) for key in _EVENT_FIELDS}
    prev = str(canonical.get("prev_hash") or "")
    blob = json.dumps(canonical, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha256((prev + blob).encode("utf-8")).hexdigest()
    sealed = dict(body)
    sealed["hash"] = digest
    for key in _EVENT_FIELDS:
        sealed[key] = canonical[key]
    return sealed


def verify_chain(rows: list[dict[str, Any]]) -> bool:
    """True when every row links to the previous hash and the digest matches."""
    prev = "0" * 64
    for row in rows:
        if str(row.get("prev_hash") or "") != prev:
            return False
        sealed = seal_event(row)
        if sealed["hash"] != row.get("hash"):
            return False
        prev = str(row["hash"])
    return True


def durable_path() -> Path | None:
    """JSONL file, or None when persistence is off (pytest default)."""
    raw = os.environ.get("QA_MANEUVER_JOURNAL_DIR")
    if raw == "-":
        return None
    if raw:
        return Path(raw) / "events.jsonl"
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    return Path(__file__).resolve().parents[4] / ".data" / "maneuver_journal" / "events.jsonl"


def append_durable(row: dict[str, Any]) -> None:
    path = durable_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_durable() -> list[dict[str, Any]]:
    path = durable_path()
    if path is None or not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def clear_durable() -> None:
    path = durable_path()
    if path is not None and path.exists():
        path.unlink()
