"""Промпт 33: релиз не выполнен, пилот не начат."""

from __future__ import annotations

import os
from pathlib import Path

os.environ["FF_QA_FOUNDER_METRICS"] = "1"
os.environ["FF_QA_SUPPORT"] = "1"
os.environ["FF_QA_SUBJECT_RIGHTS"] = "1"

from app.services.product_analytics.metrics import metrics
from app.services.product_analytics.service import reset_analytics
from app.services.qa.feature_flags import is_enabled
from app.services.subject_rights.service import delete_account, hold_for_tests, scan
from app.services.support_desk.service import (
    report,
    reset_support,
    slack_notice,
    tickets,
)


def test_release_plan_does_not_claim_a_deploy() -> None:
    root = Path(__file__).resolve().parents[3]
    text = (root / "docs" / "qa" / "RELEASE_PLAN.md").read_text(encoding="utf-8")
    assert "Прод не развёрнуто" in text
    assert "Пилот не начат" in text
    assert "2026-10-20" in text
    assert "qa_act_live" in text
    assert "нет данных" in text
    reset_analytics()
    assert metrics()["activation"] == "нет данных"
    assert is_enabled("qa_act_live") is False
    reset_support()
    body = report(
        page="/account",
        version="0",
        request_id="r33",
        errors=[],
        description="ada@example.test",
        screenshot_consent=False,
        screenshot="",
    )
    assert body["status"] == "rejected"
    assert tickets() == []
    assert slack_notice()["status"] == "нет данных"
    hold_for_tests(
        user_id="user-33",
        email="ada@example.test",
        name="AdaPerson",
        token="broker-token-33",
        consent="yes",
    )
    delete_account("user-33")
    assert scan("ada@example.test") == []
    assert scan("AdaPerson") == []
    assert scan("broker-token-33") == []


def test_release_test_does_not_import_app_main() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    lines = [line.strip() for line in source.splitlines()]
    assert not any(line.startswith("import app.main") for line in lines)
    assert not any(line.startswith("from app.main") for line in lines)
    forbidden = (
        "рекомендуем",
        "советуем",
        "подходит вам",
        "соответствует вашему профилю",
        "купите",
        "продайте",
    )
    plan = (
        Path(__file__).resolve().parents[3] / "docs" / "qa" / "RELEASE_PLAN.md"
    ).read_text(encoding="utf-8").lower()
    for phrase in forbidden:
        assert phrase not in plan
