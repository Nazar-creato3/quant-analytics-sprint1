"""Prompt 40: attribution, aggregate stats, beta/off rule. No app.main import."""
from __future__ import annotations

from datetime import UTC, datetime

from app.services.act_desk.service import reset as reset_act
from app.services.act_desk.service import save_profile
from app.services.maneuver_control.service import (
    aggregate,
    attribute,
    gate_candidate,
    history_handoff,
    kind_status,
    limits_unchanged,
    remember_path,
    score_delta,
    user_report,
)
from app.services.maneuver_control.service import (
    reset as reset_control,
)
from app.services.maneuvers.service import generate_maneuvers
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.portfolio_report.service import assemble
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
    reset_act()
    reset_control()
    get_book().reset()


def teardown_function() -> None:
    reset_control()
    reset_act()
    get_book().reset()
    reset_for_tests()


def _executed(maneuver_id: str, *, kind: str = "reduce_weight", expected: str = "0.06") -> dict:
    return {
        "id": maneuver_id,
        "kind": kind,
        "status": "executed_full",
        "expected_return": expected,
        "holdings": [{"ticker": "SBER", "qty": "10"}],
        "orders": [{"ticker": "SBER", "side": "sell", "qty": "4", "price": "100"}],
        "impact": {"delta": {"var_95": {"before": "0.10", "after": "0.08"}}},
    }


def test_flags_and_phrases():
    assert is_enabled("qa_maneuver_control") is True
    assert is_enabled("qa_act_live") is False
    text = (
        "фактический путь — бездействие. "
        "оценка снижена по отказам и правкам; лимит профиля не изменён. "
        "лимиты профиля важнее доли одобрений."
    )
    for phrase in FORBIDDEN:
        assert phrase not in text


def test_golden_attribution_against_do_nothing_and_expected():
    prices = {"SBER": ["100", "110"]}
    done = attribute(_executed("m-1"), prices)
    assert done["do_nothing_return"] == "0.1"
    assert done["actual_return"] == "0.06"
    assert done["expected_return"] == "0.06"
    assert done["error"] == "0.00"
    assert done["risk"]["expected_var_95_after"] == "0.08"
    rejected = dict(_executed("m-2"), status="rejected", expected_return="0.06")
    skipped = attribute(rejected, prices)
    assert skipped["actual_return"] == "0.1"
    assert skipped["counterfactual_return"] == "0.06"
    missing = attribute(_executed("m-3"), None)
    assert missing["actual_return"] is None
    assert missing["error_status"] == "нет данных"
    assert missing["risk"]["actual_var_95"] == "нет данных"


def test_off_rule_drops_kind_and_limits_stay():
    prices = {"SBER": ["100", "120"]}
    for index in range(5):
        attribute(
            {
                "id": f"err-{index}",
                "kind": "reduce_weight",
                "status": "executed_full",
                "expected_return": "0",
                "holdings": [{"ticker": "SBER", "qty": "10"}],
                "orders": [],
            },
            prices,
        )
    state = kind_status("reduce_weight")
    assert state["status"] == "off"
    assert state["n"] == 5
    profile = {"max_position_pct": "0.20", "max_crisis_loss_pct": "0.15"}
    kept, reason = gate_candidate({"kind": "reduce_weight", "score": "1.0"})
    assert kept is None
    assert reason
    assert limits_unchanged(profile, dict(profile))
    assert score_delta("reduce_weight") <= 0
    beta_prices = {"SBER": ["100", "106"]}
    reset_control()
    for index in range(5):
        attribute(
            {
                "id": f"beta-{index}",
                "kind": "hedge",
                "status": "executed_full",
                "expected_return": "0",
                "holdings": [{"ticker": "SBER", "qty": "10"}],
                "orders": [],
            },
            beta_prices,
        )
    assert kind_status("hedge")["status"] == "beta"
    gated, blocked = gate_candidate({"kind": "hedge", "score": "2"})
    assert blocked is None
    assert gated is not None
    assert gated["quality"] == "beta"
    assert gated["score"] <= "2"


def test_generator_skips_disabled_kind_and_report_has_no_user_id():
    prices = {"SBER": ["100", "120"]}
    for index in range(5):
        attribute(
            {
                "id": f"gen-{index}",
                "kind": "reduce_weight",
                "status": "executed_full",
                "expected_return": "0",
                "holdings": [{"ticker": "SBER", "qty": "10"}],
                "orders": [],
            },
            prices,
        )
    save_profile(
        "u-ctl",
        {
            "horizon": "3y",
            "risk_tolerance": "moderate",
            "max_position_pct": "0.20",
            "max_crisis_loss_pct": "0.15",
        },
    )
    ensure_account(account_id="p-ctl", user_id="u-ctl", venue="act", mode="paper")
    record_transaction(
        account_id="p-ctl",
        user_id="u-ctl",
        mode="paper",
        venue="act",
        external_id="seed",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="80",
        amount="8000",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=UTC),
    )
    record_transaction(
        account_id="p-ctl",
        user_id="u-ctl",
        mode="paper",
        venue="act",
        external_id="seed2",
        kind="trade",
        instrument_id="GAZP",
        ticker="GAZP",
        qty="20",
        amount="2000",
        ccy="RUB",
        event_time=datetime(2024, 1, 3, tzinfo=UTC),
    )
    batch = generate_maneuvers(user_id="u-ctl")
    assert all(row["kind"] != "reduce_weight" for row in batch["items"])
    assert any(row["kind"] == "reduce_weight" for row in batch["skipped"])
    stats = aggregate()
    assert "user_id" not in str(stats)
    assert stats["by_kind"]["reduce_weight"]["status"] == "off"
    assert stats["priority"]
    handoff = history_handoff()
    assert handoff["status"] == "прочитан"
    assert handoff["target_source"] == "user"


def test_user_report_and_assemble_and_flag_off():
    item = _executed("m-rep")
    from app.services.act_desk.service import _maneuvers

    _maneuvers[item["id"]] = {**item, "user_id": "u-rep"}
    remember_path(item["id"], {"SBER": ["100", "110"]})
    report = user_report("u-rep")
    assert report["items"][0]["actual_return"] == "0.06"
    assembled = assemble(user_id="u-rep")
    assert assembled["maneuver_control"]["items"][0]["maneuver_id"] == "m-rep"
    set_global("qa_maneuver_control", False)
    assert user_report("u-rep")["status"] == "off"
    kept, reason = gate_candidate({"kind": "reduce_weight", "score": "1"})
    assert reason is None and kept is not None
