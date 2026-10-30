"""CI guard: every AuditAction.* reference must resolve to a defined member."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = APP_ROOT / "utils" / "audit.py"


def _audit_action_members() -> set[str]:
    src = AUDIT_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"^\s+([A-Z][A-Z0-9_]*)\s*=", src, re.MULTILINE))


def _audit_action_references() -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for path in APP_ROOT.rglob("*.py"):
        if path == AUDIT_PATH:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"(?<![\w.])AuditAction\.([A-Z][A-Z0-9_]*)", text):
            member = match.group(1)
            refs.setdefault(member, set()).add(str(path.relative_to(APP_ROOT)))
    return refs


def test_audit_action_references_resolve() -> None:
    defined = _audit_action_members()
    refs = _audit_action_references()
    missing = sorted(member for member in refs if member not in defined)
    assert not missing, f"Undefined AuditAction members referenced: {missing}"


def test_order_submit_typo_would_be_caught() -> None:
    defined = _audit_action_members()
    refs = _audit_action_references()
    assert "ORDER_SUBMIT" not in defined
    if "ORDER_SUBMIT" in refs:
        pytest.fail("ORDER_SUBMIT still referenced in codebase")
