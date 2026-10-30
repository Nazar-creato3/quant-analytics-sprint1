"""D-18-1: profile, immutable journal, paper-only execute, live lawyer gate."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.act_desk.service import (
    decide,
    execute,
    get_profile,
    journal_for,
    preview_trade,
    propose,
    reset,
    save_profile,
    save_rules,
)
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global


def setup_function() -> None:
    reset_for_tests()
    reset()
    get_book().reset()


def teardown_function() -> None:
    reset()
    get_book().reset()
    reset_for_tests()


def _profile(user_id: str = "u-act") -> None:
    save_profile(
        user_id,
        {
            "horizon": "3y",
            "risk_tolerance": "moderate",
            "max_position_pct": "0.20",
            "max_crisis_loss_pct": "0.15",
        },
    )


def _overweight(user_id: str = "u-act") -> None:
    ensure_account(account_id="p-act", user_id=user_id, venue="act", mode="paper")
    record_transaction(
        account_id="p-act",
        user_id=user_id,
        mode="paper",
        venue="act",
        external_id="seed",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="80",
        amount="8000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    record_transaction(
        account_id="p-act",
        user_id=user_id,
        mode="paper",
        venue="act",
        external_id="seed2",
        kind="trade",
        instrument_id="GAZP",
        ticker="GAZP",
        qty="20",
        amount="2000",
        ccy="RUB",
        event_time=datetime(2024, 1, 3, tzinfo=timezone.utc),
    )


def test_propose_needs_profile():
    out = propose(user_id="nobody")
    assert out["empty"] is True
    assert "анкета" in out["reason"]


def test_rule_maneuver_edit_approve_paper_and_live_block():
    _profile()
    save_rules("u-act", {"max_single_weight": "0.25"})
    _overweight()
    batch = propose(user_id="u-act")
    assert batch["empty"] is False
    reduce = next(i for i in batch["items"] if i["kind"] == "reduce_weight")
    assert reduce["logic"]["phrase"]
    assert "купите" not in reduce["rationale"].lower()
    viewed = decide(user_id="u-act", maneuver_id=reduce["id"], action="view")
    assert viewed["status"] == "viewed"
    edited = decide(user_id="u-act", maneuver_id=reduce["id"], action="edit", edits={"qty": "0.10"})
    assert edited["status"] == "edited"
    assert edited["qty"] == "0.10"
    with pytest.raises(ValueError):
        execute(user_id="u-act", maneuver_id=reduce["id"], mode="paper")
    approved = decide(user_id="u-act", maneuver_id=reduce["id"], action="approve", confirm=True)
    assert approved["status"] == "approved"
    done = execute(user_id="u-act", maneuver_id=reduce["id"], mode="paper")
    assert done["status"] == "executed_full"
    with pytest.raises(PermissionError):
        execute(user_id="u-act", maneuver_id=reduce["id"], mode="live")
    rows = journal_for("u-act")
    assert rows[0]["prev_hash"] == "0" * 64
    assert rows[-1]["prev_hash"] == rows[-2]["hash"]
    assert get_profile("u-act")["horizon"] == "3y"


def test_preview_and_api():
    _profile("demo")
    _overweight("demo")
    preview = preview_trade(user_id="demo", ticker="SBER", qty="1", price="100")
    assert "hhi" in preview["delta"]
    assert "var_95" in preview["delta"]
    assert "stress_worst" in preview["delta"]
    from app.tests.qa_session import bind_session_user, clear_session_user

    bind_session_user("demo")
    client = TestClient(app)
    body = client.post("/api/v1/act/propose", params={"user_id": "demo"}).json()
    assert body["model_version"] == "act_desk.v1"
    journal = client.get("/api/v1/act/journal", params={"user_id": "demo"}).json()
    assert journal["source"] == "act_desk"
    assert journal["items"]
    set_global("qa_act_live", False)
    live = client.post("/api/v1/act/execute", json={"user_id": "demo", "maneuver_id": "missing", "mode": "live"})
    assert live.status_code in {400, 403}
    clear_session_user()
