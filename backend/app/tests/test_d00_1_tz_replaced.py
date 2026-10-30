"""D-00-1 / OQ-00-1 closed: TZ 1.0 is replaced by the listed documents."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_tz_file_is_toc_not_stub():
    text = _text("docs/qa/QA-TZ-target-architecture.md")
    assert "ТЗ 1.0 заменено перечисленными документами" in text
    assert "docs/qa/DECISIONS.md" in text or "./DECISIONS.md" in text
    assert "QA-TZ-addendum-1.1.md" in text
    assert "QA-CURSOR-FULL-PROMPT-SET-v1.1.md" in text
    assert "QA-CURSOR-PROMPT-SET-v1.2-addendum.md" in text
    assert "Замените этот файл полным текстом ТЗ 1.0" not in text
    assert "не найдено" not in text


def test_d00_1_and_oq00_1_are_closed():
    decisions = _text("docs/qa/DECISIONS_PENDING.md")
    questions = _text("docs/qa/OPEN_QUESTIONS.md")
    progress = _text("docs/qa/PROGRESS.md")
    index = _text("docs/qa/reports/INDEX.md")
    assert "| D-00-1 |" in decisions
    assert "**решено 2026-10-06**" in decisions.split("| D-00-1 |", 1)[1].split("\n", 1)[0]
    assert "Закрыто 2026-10-06 (D-00-1)" in questions
    open_line = next(line for line in progress.splitlines() if line.startswith("**Ожидает решения:**"))
    assert "D-00-1" not in open_line
    assert "OQ-00-1" not in open_line
    assert "35 | в работе" not in index
    assert "в работе (`qa/35-investment-profile`)" not in progress
