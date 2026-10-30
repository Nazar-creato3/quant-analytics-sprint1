"""Resolve env vars from the process environment with a backend/.env fallback.

Pydantic ``Settings`` only maps a fixed set of fields; venue credentials and
other operator-provided keys live in ``backend/.env`` but are not always
exported into ``os.environ``. This helper mirrors the pattern used by
``app.services.ops.pilot_status`` so venue/ops code can read those keys without
depending on the Settings schema.

Never logs values — callers must treat returned strings as secret material.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values


def _backend_dir() -> Path:
    # app/utils/env_file.py -> parents[2] == backend/
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _dotenv_file() -> dict[str, str | None]:
    path = _backend_dir() / ".env"
    if path.is_file():
        return dotenv_values(path)
    return {}


def env_value(key: str, default: str | None = None) -> str | None:
    """Return ``key`` from process env, then backend/.env, then ``default``.

    Empty / whitespace-only process values do not block ``backend/.env`` —
    root ``.env`` often ships blank ``BINANCE_*`` placeholders that would
    otherwise shadow real keys in ``backend/.env``.
    """
    value = os.getenv(key)
    if value is not None and value.strip():
        return value
    file_val = _dotenv_file().get(key)
    if file_val is not None and str(file_val).strip():
        return file_val
    return default


def env_nonempty(*keys: str) -> bool:
    """True if any of ``keys`` resolves to a non-empty (stripped) value."""
    return any((env_value(key) or "").strip() for key in keys)
