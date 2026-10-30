"""Resolve repo / third_party paths without importing clones onto sys.path by default."""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """apex-intel repo root (…/apex-intel).

    Override with APEX_INTEL_ROOT when running from unusual layouts (Docker, tests).
    """
    override = os.environ.get("APEX_INTEL_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    # backend/app/services/crypto_stack/integrations/paths.py → 5 parents up = repo
    return Path(__file__).resolve().parents[5]


def third_party_root() -> Path:
    override = os.environ.get("APEX_THIRD_PARTY_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    return repo_root() / "third_party"


def third_party_path(dirname: str) -> Path:
    return third_party_root() / dirname


def path_status(dirname: str) -> dict:
    """Common installed-path fields for adapters."""
    path = third_party_path(dirname)
    exists = path.is_dir()
    return {
        "path": str(path),
        "installed": exists,
        "path_exists": exists,
    }
