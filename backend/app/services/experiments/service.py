"""Experiment assignments stay off until a founder decision exists."""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

from app.services.qa.feature_flags import is_enabled

_MISSING = "нет данных"
_Z = Decimal("1.96") + Decimal("0.84")
_CONFIG = Path(__file__).with_name("config.json")
_journal: list[dict[str, str]] = []
_decision: dict[str, Any] | None = None


def reset_experiments() -> None:
    global _decision
    _journal.clear()
    _decision = None


def set_founder_decision_for_tests(decision: dict[str, Any] | None) -> None:
    global _decision
    _decision = decision


def _decision_row() -> dict[str, Any] | None:
    if _decision is not None:
        return _decision
    raw = json.loads(_CONFIG.read_text(encoding="utf-8")).get("founder_decision")
    if not isinstance(raw, dict) or not raw:
        return None
    return raw


def _pseudo(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]


def status() -> dict[str, str]:
    if not is_enabled("qa_experiments"):
        return {"status": "off"}
    row = _decision_row()
    if row is None:
        return {"status": "rejected", "reason": _MISSING}
    name = row.get("name")
    return {"status": "ready", "experiment": name if isinstance(name, str) and name else _MISSING}


def assign(subject: str) -> dict[str, str]:
    if not is_enabled("qa_experiments"):
        return {"status": "off"}
    row = _decision_row()
    if row is None or not subject or "@" in subject:
        return {"status": "rejected", "reason": _MISSING}
    split = row.get("split")
    name = row.get("name")
    if not isinstance(split, int) or not isinstance(name, str) or not name:
        return {"status": "rejected", "reason": _MISSING}
    pseudo = _pseudo(subject)
    for existing in _journal:
        if existing["experiment"] == name and existing["subject_pseudo"] == pseudo:
            return {"status": "ok", "variant": existing["variant"], "subject_pseudo": pseudo}
    digest = hashlib.sha256(f"{name}:{subject}".encode()).hexdigest()
    variant = "b" if int(digest[:8], 16) % 100 < split else "a"
    _journal.append({"experiment": name, "subject_pseudo": pseudo, "variant": variant})
    return {"status": "ok", "variant": variant, "subject_pseudo": pseudo}


def journal() -> list[dict[str, str]]:
    return [dict(row) for row in _journal]


def sample_size(*, baseline: str | None = None, effect: str | None = None) -> str:
    if baseline in (None, "") or effect in (None, ""):
        return _MISSING
    base = Decimal(baseline)
    delta = Decimal(effect)
    other = base + delta
    if not (Decimal(0) < base < Decimal(1) and Decimal(0) < other < Decimal(1)):
        return _MISSING
    variance = base * (1 - base) + other * (1 - other)
    sized = (_Z * _Z * variance / (delta * delta)).to_integral_value(rounding=ROUND_CEILING)
    return str(sized)


def verdict(
    *,
    successes_a: int,
    n_a: int,
    successes_b: int,
    n_b: int,
    required: int | None,
    errors: int,
    error_ceiling: int | None,
    breaches: int,
    breach_ceiling: int | None,
) -> dict[str, str]:
    if required is None or error_ceiling is None or breach_ceiling is None:
        return {"winner": _MISSING, "reason": "threshold"}
    if n_a < required or n_b < required:
        return {"winner": _MISSING, "reason": "sample"}
    if errors > error_ceiling or breaches > breach_ceiling:
        return {"winner": _MISSING, "reason": "guardrail"}
    left = successes_a * n_b
    right = successes_b * n_a
    if left == right:
        return {"winner": _MISSING, "reason": "tie"}
    return {"winner": "a" if left > right else "b", "reason": "counts"}
