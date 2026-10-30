"""Prompt 41: version ledger and journal replay. Does not import app.main."""
from __future__ import annotations

from pathlib import Path

from app.services.accreditation.service import (
    code_versions,
    replay_from_journal,
    versions_match,
)
from app.services.maneuver_cycle.journal import seal_event, verify_chain
from app.services.qa.feature_flags import is_enabled

_FORBIDDEN = (
    "рекомендуем",
    "советуем",
    "подходит вам",
    "соответствует вашему профилю",
    "купите",
    "продайте",
)


def test_live_stays_off_and_versions_match_ledger():
    assert is_enabled("qa_act_live") is False
    assert versions_match() is True
    drifted = dict(code_versions())
    drifted["maneuvers"] = "maneuvers.v2"
    assert versions_match(drifted) is False


def test_sealed_version_is_immutable_and_replay_does_not_recompute():
    body = seal_event(
        {
            "id": "e1",
            "user_id": "u1",
            "name": "proposed",
            "payload": {
                "maneuver": {
                    "kind": "reduce_weight",
                    "orders": [{"ticker": "SBER", "side": "sell", "qty": "4"}],
                    "rationale": "доля выше лимита профиля",
                }
            },
            "model_version": "act_desk.v1",
            "at": "2026-10-07T00:00:00Z",
            "prev_hash": "0" * 64,
            "profile_snapshot": {"max_position_pct": "0.20"},
            "model_versions": {"maneuvers": "maneuvers.v1"},
            "shown_text": "доля выше лимита профиля",
        }
    )
    assert verify_chain([body]) is True
    changed = dict(body)
    changed["model_version"] = "act_desk.v2"
    assert verify_chain([changed]) is False
    replay = replay_from_journal(body)
    assert replay["orders"] == [{"ticker": "SBER", "side": "sell", "qty": "4"}]
    assert replay["model_version"] == "act_desk.v1"
    assert replay["model_versions"]["maneuvers"] == "maneuvers.v1"
    assert replay["profile_snapshot"]["max_position_pct"] == "0.20"
    assert replay["hash"] == body["hash"]


def test_pack_texts_avoid_forbidden_phrases():
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / "docs" / "legal" / "accreditation" / "requirements.md",
        root / "docs" / "legal" / "accreditation" / "mapping.md",
        root / "docs" / "legal" / "accreditation" / "drafts" / "01-program-mechanism.md",
        root / "docs" / "legal" / "accreditation" / "drafts" / "02-documents-for-lawyer.md",
        Path(__file__).resolve().parents[1] / "services" / "accreditation" / "service.py",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        for phrase in _FORBIDDEN:
            assert phrase not in text, path.name
