"""Prompt 30: local checksum budget. The 1000-user run is not executed."""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from app.services.perf_budget.service import budget_run, last_budget, reset
from app.services.qa.feature_flags import is_enabled, reset_for_tests

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")


def setup_function() -> None:
    reset_for_tests()
    reset()


def teardown_function() -> None:
    reset_for_tests()
    reset()


def test_local_budget_matches_independent_checksum() -> None:
    assert is_enabled("qa_perf_budget") is True
    assert is_enabled("qa_act_live") is False
    first = budget_run()
    second = budget_run()
    assert first["checksum"] == "4000"
    assert second["checksum"] == "4000"
    assert Decimal(first["elapsed_ms"]) < Decimal(first["ceiling_ms"])
    assert Decimal(second["elapsed_ms"]) < Decimal(second["ceiling_ms"])
    assert first["users_executed"] == "1000"
    assert first["database_profile"] == "нет данных"
    assert first["worker_limits"] == "нет данных"
    assert first["target_users"] == "1000"
    assert last_budget()["checksum"] == "4000"
    print(f"PERF_BEFORE_MS={first['elapsed_ms']} PERF_AFTER_MS={second['elapsed_ms']}")


def test_flag_off_skips_the_loop() -> None:
    os.environ["FF_QA_PERF_BUDGET"] = "0"
    assert budget_run()["status"] == "off"


def test_perf_texts_omit_forbidden_phrases() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "app" / "services" / "perf_budget" / "service.py").read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN:
        assert phrase not in text
