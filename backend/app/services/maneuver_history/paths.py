"""Repository paths for the offline maneuver-history run."""
from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def golden_dir() -> Path:
    return repo_root() / "docs" / "qa" / "golden"


def delist_path() -> Path:
    return repo_root() / "docs" / "qa" / "delistings.json"


def report_path() -> Path:
    return repo_root() / "docs" / "models" / "maneuvers-validation.md"


def control_path() -> Path:
    return repo_root() / "docs" / "models" / "maneuver-history-control.json"
