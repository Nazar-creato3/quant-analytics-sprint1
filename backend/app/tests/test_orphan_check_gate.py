from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_orphan_check_baseline_mode():
    script = REPO / "scripts" / "orphan_check.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "orphan_check:" in proc.stdout
