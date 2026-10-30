"""E46-17 + D-00-2 closed: canon lives in DECISIONS.md."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CANON = REPO / "docs" / "qa" / "DECISIONS.md"
INDEX = REPO / "docs" / "qa" / "FOUNDER-DECISIONS.md"


def test_e46_17_founder_decisions_lists_r1_r14_without_inventing_gaps():
    text = CANON.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")
    assert "D-00-2" in text
    assert "D-18-1" in text
    for n in range(1, 15):
        assert f"| Р{n} |" in text
        assert f"| Р{n} |" in index
    assert "текста нет" in text
    assert "qa_act_live" in text
