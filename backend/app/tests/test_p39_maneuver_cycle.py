"""Prompt 39: approval cycle, hash chain, paper fill. Does not import app.main."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.services.act_desk.service import (
    _journal,
    close_maneuver,
    decide,
    execute,
    export_maneuver_pdf,
    journal_for,
    list_maneuvers,
    propose,
    reload_journal,
    reset,
    save_profile,
    send,
)
from app.services.explanations.service import filter_wording
from app.services.maneuver_cycle.journal import verify_chain
from app.services.maneuver_cycle.machine import TransitionError, assert_transition
from app.services.maneuver_cycle.service import diff_composition, recheck_before_send
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled, reset_for_tests, set_global

FORBIDDEN = (
    "рекомендуем",
    "советуем",
    "подходит вам",
    "соответствует вашему профилю",
    "купите",
    "продайте",
)


def setup_function() -> None:
    reset_for_tests()
    reset()
    get_book().reset()


def teardown_function() -> None:
    reset()
    get_book().reset()
    reset_for_tests()


def _profile(user_id: str = "u-cycle") -> None:
    save_profile(
        user_id,
        {
            "horizon": "3y",
            "risk_tolerance": "moderate",
            "max_position_pct": "0.20",
            "max_crisis_loss_pct": "0.15",
        },
    )


def _book(user_id: str = "u-cycle") -> None:
    ensure_account(account_id="p-cycle", user_id=user_id, venue="act", mode="paper")
    record_transaction(
        account_id="p-cycle",
        user_id=user_id,
        mode="paper",
        venue="act",
        external_id="seed-sber",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="80",
        amount="8000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=UTC),
    )
    record_transaction(
        account_id="p-cycle",
        user_id=user_id,
        mode="paper",
        venue="act",
        external_id="seed-gazp",
        kind="trade",
        instrument_id="GAZP",
        ticker="GAZP",
        qty="20",
        amount="2000",
        ccy="RUB",
        event_time=datetime(2024, 1, 3, tzinfo=UTC),
    )


def _reduce(user_id: str = "u-cycle") -> dict:
    _profile(user_id)
    _book(user_id)
    batch = propose(user_id=user_id)
    return next(row for row in batch["items"] if row["kind"] == "reduce_weight")


def test_flags_live_off_cycle_on():
    assert is_enabled("qa_maneuver_cycle") is True
    assert is_enabled("qa_act_live") is False


def test_forbidden_transition_and_confirm():
    item = _reduce()
    with pytest.raises(ValueError):
        decide(user_id="u-cycle", maneuver_id=item["id"], action="approve", confirm=True)
    with pytest.raises(TransitionError):
        assert_transition("closed", "sent")
    with pytest.raises(TransitionError):
        assert_transition("rejected", "approved")
    viewed = decide(user_id="u-cycle", maneuver_id=item["id"], action="view")
    with pytest.raises(ValueError, match="подтверждение"):
        decide(user_id="u-cycle", maneuver_id=viewed["id"], action="approve", confirm=False)


def test_reject_requires_listed_reason_and_blocks_later_approve():
    item = _reduce()
    decide(user_id="u-cycle", maneuver_id=item["id"], action="view")
    with pytest.raises(ValueError):
        decide(user_id="u-cycle", maneuver_id=item["id"], action="reject", reject_reason="mood")
    with pytest.raises(ValueError):
        decide(
            user_id="u-cycle",
            maneuver_id=item["id"],
            action="reject",
            reject_reason="other",
            reject_note="",
        )
    rejected = decide(
        user_id="u-cycle",
        maneuver_id=item["id"],
        action="reject",
        reject_reason="size",
        reject_note="размер больше лимита, который я задал",
    )
    assert rejected["status"] == "rejected"
    assert rejected["reject_reason_label"] == "размер"
    assert filter_wording(rejected["reject_note"]) == []
    with pytest.raises(ValueError):
        decide(user_id="u-cycle", maneuver_id=item["id"], action="approve", confirm=True)


def test_paper_cycle_partial_then_full_then_close():
    item = _reduce()
    edited = decide(user_id="u-cycle", maneuver_id=item["id"], action="view")
    edited = decide(user_id="u-cycle", maneuver_id=item["id"], action="edit", edits={"qty": "2"})
    assert edited["version"] == 2
    assert edited["diff_vs_original"]
    assert edited["impact"].get("gate")
    assert edited["impact"].get("delta")
    for phrase in FORBIDDEN:
        assert phrase not in str(edited["rationale"]).lower()
    approved = decide(user_id="u-cycle", maneuver_id=item["id"], action="approve", confirm=True)
    assert approved["confirmed"] is True
    sent = send(user_id="u-cycle", maneuver_id=item["id"])
    assert sent["status"] == "sent"
    assert sent["price_check"]["ok"] is True
    partial = execute(user_id="u-cycle", maneuver_id=item["id"], filled_qty="1")
    assert partial["status"] == "executed_partial"
    ordered = Decimal(partial["ordered_qty"])
    rest = format(ordered - Decimal(1), "f")
    done = execute(user_id="u-cycle", maneuver_id=item["id"], filled_qty=rest)
    assert done["status"] == "executed_full"
    assert done["idempotency_key"].startswith(f"act:{item['id']}:")
    closed = close_maneuver(user_id="u-cycle", maneuver_id=item["id"])
    assert closed["status"] == "closed"
    with pytest.raises(ValueError):
        execute(user_id="u-cycle", maneuver_id=item["id"], mode="paper")
    listed = list_maneuvers("u-cycle", status="closed")
    assert len(listed) == 1
    rows = journal_for("u-cycle")
    assert verify_chain(rows) is True
    assert rows[0]["prev_hash"] == "0" * 64
    assert rows[-1]["profile_snapshot"]["horizon"] == "3y"
    assert rows[-1]["shown_text"]
    tampered = [dict(row) for row in rows]
    tampered[1]["shown_text"] = "изменено"
    assert verify_chain(tampered) is False
    pdf = export_maneuver_pdf("u-cycle", item["id"])
    assert pdf is not None and pdf.startswith(b"%PDF")
    assert len(pdf) > 200


def test_missing_price_does_not_send():
    blocked = recheck_before_send({"orders": [], "expires_at": "2099-01-01T00:00:00+00:00"})
    assert blocked["ok"] is False
    assert blocked["reason"] == "нет данных"
    changes = diff_composition(
        [{"ticker": "SBER", "qty": "1", "side": "sell"}],
        [{"ticker": "SBER", "qty": "2", "side": "sell"}],
    )
    assert changes[0]["before"] == "1"
    assert changes[0]["after"] == "2"


def test_live_stays_refused_even_if_lawyer_flag_on():
    item = _reduce()
    decide(user_id="u-cycle", maneuver_id=item["id"], action="view")
    decide(user_id="u-cycle", maneuver_id=item["id"], action="approve", confirm=True)
    with pytest.raises(PermissionError):
        execute(user_id="u-cycle", maneuver_id=item["id"], mode="live")
    set_global("qa_act_live", True)
    with pytest.raises(PermissionError, match="24"):
        execute(user_id="u-cycle", maneuver_id=item["id"], mode="live")


def test_flag_off_restores_direct_edit(monkeypatch, tmp_path):
    monkeypatch.setenv("QA_MANEUVER_JOURNAL_DIR", str(tmp_path))
    reset()
    item = _reduce()
    set_global("qa_maneuver_cycle", False)
    edited = decide(user_id="u-cycle", maneuver_id=item["id"], action="edit", edits={"qty": "0.05"})
    assert edited["status"] == "edited"
    decide(user_id="u-cycle", maneuver_id=item["id"], action="approve")
    done = execute(user_id="u-cycle", maneuver_id=item["id"], mode="paper")
    assert done["status"] == "executed_paper"
    rows = journal_for("u-cycle")
    assert verify_chain(rows) is True
    _journal.clear()
    assert reload_journal() >= 1
    reloaded = journal_for("u-cycle")
    assert [row["hash"] for row in reloaded] == [row["hash"] for row in rows]
