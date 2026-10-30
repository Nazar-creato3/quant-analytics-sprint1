"""Small durable JSON store for per-user state that used to live in process memory.

Several services kept user state in module-level dicts. With two uvicorn workers
and container restarts that state vanished or differed per request (a saved
investment profile looked empty on the next page). This keeps a JSON file per
store under ``DURABLE_STORE_DIR`` (default ``/app/data/state``, the bind-mounted
data volume), with an exclusive lock so both workers see the same data.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


_MEMORY: dict[str, dict[str, Any]] = {}


def enabled() -> bool:
    """File-backed in production/staging (or QA_STATE_PERSIST=1); plain memory in tests and dev."""
    flag = os.environ.get("QA_STATE_PERSIST", os.environ.get("QA_BOOK_PERSIST", "")).strip().lower()
    if flag in {"0", "false", "no"}:
        return False
    if flag in {"1", "true", "yes"}:
        return True
    return os.environ.get("APP_ENV", "").strip().lower() in {"production", "staging"}


def _root() -> Path:
    env = os.environ.get("DURABLE_STORE_DIR", "").strip()
    candidates = [Path(env)] if env else []
    candidates += [Path("/app/data/state"), Path(__file__).resolve().parents[3] / "data" / "state"]
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return cand
        except OSError:
            continue
    return Path(tempfile.gettempdir()) / "qa-state"


def _path(name: str) -> Path:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{name}.json"


@contextmanager
def _locked(name: str) -> Iterator[Path]:
    path = _path(name)
    lock_path = path.with_suffix(".lock")
    with open(lock_path, "a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield path
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load(name: str) -> dict[str, Any]:
    if not enabled():
        return dict(_MEMORY.get(name) or {})
    with _locked(name) as path:
        return _read(path)


def update(name: str, key: str, value: Any) -> None:
    """Set ``key`` (None deletes it) atomically."""
    if not enabled():
        mem = _MEMORY.setdefault(name, {})
        if value is None:
            mem.pop(key, None)
        else:
            mem[key] = value
        return
    with _locked(name) as path:
        data = _read(path)
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, path)


def save(name: str, data: dict[str, Any]) -> None:
    """Replace the whole store atomically."""
    if not enabled():
        _MEMORY[name] = dict(data)
        return
    with _locked(name) as path:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, path)


def clear(name: str) -> None:
    if not enabled():
        _MEMORY.pop(name, None)
        return
    with _locked(name) as path:
        path.unlink(missing_ok=True)
