from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import architecture_lint  # noqa: E402


def test_baseline_check_passes_on_current_tree():
    hits = architecture_lint.scan()
    baseline = architecture_lint.load_baseline()
    new = [h for h in hits if architecture_lint.key(h) not in baseline]
    assert new == []


def test_artificial_validation_import_is_caught():
    # File under app.api so no_validation_in_prod fires.
    app_api = REPO / "backend" / "app" / "api"
    probe = app_api / "_qa_probe_forbidden_import.py"
    probe.write_text("import validation.run_audit\n", encoding="utf-8")
    try:
        hits = architecture_lint.scan()
        assert any(
            h["rule"] == "no_validation_in_prod" and h["file"].endswith("_qa_probe_forbidden_import.py")
            for h in hits
        )
        baseline = architecture_lint.load_baseline()
        new = [h for h in hits if architecture_lint.key(h) not in baseline]
        assert new
    finally:
        probe.unlink(missing_ok=True)
