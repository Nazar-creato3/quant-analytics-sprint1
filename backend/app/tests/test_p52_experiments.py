"""Prompt 52: assignments are stable, and a small sample names no winner."""
from __future__ import annotations

import json
import os
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from app.api.v1.endpoints.experiments import post_experiment_assign
from app.services.experiments.service import (
    assign,
    journal,
    reset_experiments,
    sample_size,
    set_founder_decision_for_tests,
    status,
    verdict,
)
from app.services.forecast_log.store import get_store
from app.services.product_analytics.metrics import metrics, weekly_summary
from app.services.product_analytics.service import reset_analytics
from app.services.public_accuracy.service import public_accuracy
from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.subscription_billing.service import quote

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
REPO = Path(__file__).resolve().parents[3]


def setup_function() -> None:
    reset_for_tests()
    reset_experiments()
    reset_analytics()
    get_store().reset()


def teardown_function() -> None:
    reset_for_tests()
    reset_experiments()
    reset_analytics()
    get_store().reset()


def test_experiments_stay_off_without_a_decision() -> None:
    assert is_enabled("qa_experiments") is False
    assert is_enabled("qa_preorder") is False
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_partners") is False
    assert is_enabled("qa_partner_ads") is False
    assert status()["status"] == "off"
    assert sample_size() == "нет данных"
    assert public_accuracy()["accuracy"] == "нет данных"
    assert metrics()["activation"] == "нет данных"
    assert weekly_summary()["status"] == "нет данных"
    assert quote(user_id="p52", plan="personal", period="month")["amount"] == "10000"
    empty = verdict(
        successes_a=9,
        n_a=10,
        successes_b=1,
        n_b=10,
        required=None,
        errors=0,
        error_ceiling=None,
        breaches=0,
        breach_ceiling=None,
    )
    assert empty["winner"] == "нет данных"


def test_assignment_is_stable_and_small_samples_have_no_winner() -> None:
    os.environ["FF_QA_EXPERIMENTS"] = "1"
    assert status()["reason"] == "нет данных"
    set_founder_decision_for_tests({"name": "copy", "split": 50})
    first: dict[str, str] = {}
    for index in range(200):
        subject = f"subject-{index}"
        row = assign(subject)
        assert row["status"] == "ok"
        assert row["variant"] == assign(subject)["variant"]
        first[subject] = row["variant"]
    variants = set(first.values())
    assert variants == {"a", "b"}
    posted = post_experiment_assign({"subject": "a@b.c"})
    assert posted["status"] == "rejected"
    assert "subject_pseudo" not in posted
    blob = json.dumps(journal())
    assert "a@b.c" not in blob
    assert "@" not in blob
    assert "subject-0" not in blob
    base = Decimal("0.5")
    delta = Decimal("0.1")
    other = base + delta
    variance = base * (1 - base) + other * (1 - other)
    zed = Decimal("1.96") + Decimal("0.84")
    expected = (zed * zed * variance / (delta * delta)).to_integral_value(rounding=ROUND_CEILING)
    assert sample_size(baseline="0.5", effect="0.1") == str(expected)
    small = verdict(
        successes_a=3,
        n_a=3,
        successes_b=0,
        n_b=3,
        required=int(expected),
        errors=0,
        error_ceiling=1,
        breaches=0,
        breach_ceiling=1,
    )
    assert small["winner"] == "нет данных"
    assert small["reason"] == "sample"
    blocked = verdict(
        successes_a=8,
        n_a=10,
        successes_b=2,
        n_b=10,
        required=10,
        errors=4,
        error_ceiling=1,
        breaches=0,
        breach_ceiling=1,
    )
    assert blocked["reason"] == "guardrail"
    named = verdict(
        successes_a=8,
        n_a=10,
        successes_b=2,
        n_b=10,
        required=10,
        errors=0,
        error_ceiling=1,
        breaches=0,
        breach_ceiling=1,
    )
    assert named["winner"] == "a"
    for rel in (
        "backend/app/services/experiments/service.py",
        "frontend/src/lib/experiments.ts",
        "docs/methodology/experiments.md",
    ):
        text = (REPO / rel).read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN:
            assert phrase not in text
