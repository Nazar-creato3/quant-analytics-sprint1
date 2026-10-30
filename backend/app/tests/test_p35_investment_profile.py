"""User risk settings: limits, warnings, version journal; no regulated-profile fields."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.services.investment_profile.service import (
    due_for_review,
    get_profile,
    history_for,
    limits_from_profile,
    reset,
    save_profile,
    warnings_vs_portfolio,
)
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()
    reset()


def teardown_function() -> None:
    reset()
    reset_for_tests()


def _full(user_id: str = "u-p35", **extra):
    body = {
        "horizon": "5y",
        "risk_tolerance": "moderate",
        "expected_return": "0.08",
        "max_position_pct": "0.20",
        "max_crisis_loss_pct": "0.15",
        "age": "40",
        "income_12m": "120000",
        "expenses_12m": "80000",
        "savings": "500000",
        "education": "высшее",
    }
    body.update(extra)
    return save_profile(user_id, body)


def test_limits_match_golden_bands():
    golden = json.loads(
        (__import__("pathlib").Path(__file__).resolve().parents[3] / "docs/qa/golden/limits_profile_bands.json").read_text(
            encoding="utf-8"
        )
    )
    for band, expected in golden["bands"].items():
        got = limits_from_profile({"risk_tolerance": band, "max_crisis_loss_pct": "0.12", "max_position_pct": "0.15"})
        assert got["var_95"] == expected["var_95"]
        assert got["es_975"] == expected["es_975"]
        assert got["max_drawdown"] == expected["max_drawdown"]


def test_regulated_profile_fields_are_never_stored():
    """Age, income, expenses, savings, education: not accepted, not kept, not returned."""
    row = _full("u-personal")
    for key in ("age", "income_12m", "expenses_12m", "savings", "education", "complete_5014u"):
        assert key not in row
        assert key not in (get_profile("u-personal") or {})
    warns = warnings_vs_portfolio("u-personal")
    assert not any(w["code"] == "incomplete_5014u" for w in warns)

def test_iis_short_horizon_warning():
    _full(account_type="iis", iis_type="a", horizon="1y")
    codes = {w["code"] for w in warnings_vs_portfolio("u-p35")}
    assert "iis_horizon" in codes


def test_version_journal_immutable_append():
    _full()
    _full(expected_return="0.09")
    hist = history_for("u-p35")
    assert len(hist) == 2
    assert hist[0]["version"] == 1
    assert hist[1]["version"] == 2
    assert hist[0]["answers_hash"] != hist[1]["answers_hash"]
    assert get_profile("u-p35")["version"] == 2


def test_review_due_after_year():
    _full()
    later = datetime.now(timezone.utc) + timedelta(days=366)
    assert due_for_review("u-p35", now=later)["due"] is True


def test_qualified_docs_flag_off_does_not_verify():
    _full(qualified_investor=True, qualified_docs_verified=True, expected_return="0.06")
    row = get_profile("u-p35")
    assert row["qualified_investor"] is True
    assert row["qualified_docs_verified"] is False
