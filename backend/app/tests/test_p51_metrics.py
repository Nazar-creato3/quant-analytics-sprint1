"""Prompt 51: founder metrics come from the event SQL, or stay unset."""
from __future__ import annotations

import os
from pathlib import Path

from app.api.v1.endpoints.product_analytics import (
    get_founder_metrics,
    get_weekly_summary,
)
from app.services.forecast_log.store import get_store
from app.services.product_analytics.metrics import (
    export_lines,
    metrics,
    metrics_for,
    weekly_summary,
)
from app.services.product_analytics.service import reset_analytics
from app.services.public_accuracy.service import public_accuracy
from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.subscription_billing.service import quote

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
REPO = Path(__file__).resolve().parents[3]


def _row(name: str, subject: str, at: str, **props: str) -> dict:
    return {
        "name": name,
        "subject_pseudo": subject,
        "recorded_at": at,
        "properties": props,
    }


def setup_function() -> None:
    reset_for_tests()
    reset_analytics()
    get_store().reset()


def teardown_function() -> None:
    reset_for_tests()
    reset_analytics()
    get_store().reset()


def test_empty_metrics_are_not_zero() -> None:
    assert is_enabled("qa_founder_metrics") is True
    assert is_enabled("qa_preorder") is False
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_partners") is False
    assert quote(user_id="p51", plan="personal", period="month")["amount"] == "10000"
    assert public_accuracy()["accuracy"] == "нет данных"
    current = metrics()
    assert current["activation"] == "нет данных"
    assert current["retention"] == "нет данных"
    assert current["funnel"] == "нет данных"
    assert current["profile_share"] == "нет данных"
    assert current["time_to_report"] == "нет данных"
    assert current["connect_errors"] == "нет данных"
    assert current["main_target"] == "нет данных"
    assert get_founder_metrics()["activation"] == "нет данных"
    summary = weekly_summary()
    assert summary["status"] == "нет данных"
    assert "@" not in summary["text"]
    assert "email" not in summary["text"]


def test_synthetic_events_match_the_sql() -> None:
    rows = [
        _row("registration", "a", "2026-10-01 00:00:00"),
        _row("account_connect_success", "a", "2026-10-01 00:00:00", venue="moex"),
        _row("first_report_shown", "a", "2026-10-01 02:00:00"),
        _row("profile_questionnaire_completed", "a", "2026-10-01 03:00:00"),
        _row("user_return", "a", "2026-10-08 00:00:00"),
        _row("maneuver_proposed", "a", "2026-10-01 04:00:00"),
        _row("registration", "b", "2026-10-01 00:00:00"),
        _row("account_connect_success", "b", "2026-10-01 00:00:00", venue="tbank"),
        _row("first_report_shown", "b", "2026-10-03 00:00:00"),
        _row("account_connect_error", "b", "2026-10-01 01:00:00", venue="moex", reason="rejected"),
        _row("account_connect_success", "c", "2026-10-02 00:00:00", venue="finam"),
    ]
    current = metrics_for(rows)
    assert current["activation"] == "1/3"
    assert current["profile_share"] == "1/2"
    assert current["time_to_report"] == "25"
    assert current["main_metric"] == "activation"
    assert current["funnel"]["maneuver_proposed"] == "1"
    assert current["funnel"]["maneuver_executed"] == "0"
    assert current["connect_errors"] == {"moex": "1"}
    assert len(current["retention"]) == 1
    assert current["retention"][0]["users"] == "2"
    assert current["retention"][0]["returned"] == "1"
    blob = " ".join(export_lines(current))
    assert "a@" not in blob
    assert "@" not in blob
    sql = (REPO / "backend/app/services/product_analytics/metrics.sql").read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW" in sql
    page = (REPO / "docs/analytics/metrics.md").read_text(encoding="utf-8")
    for phrase in FORBIDDEN:
        assert phrase not in page.lower()
        assert phrase not in sql.lower()
    os.environ["FF_QA_FOUNDER_METRICS"] = "0"
    assert metrics_for(rows)["status"] == "off"
    # flag off: the endpoint hides itself with 404 (GA: founder analytics behind a session)
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as off:
        get_weekly_summary(_admin={"id": "founder"})
    assert off.value.status_code == 404
