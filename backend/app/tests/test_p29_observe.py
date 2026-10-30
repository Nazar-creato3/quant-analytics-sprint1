"""Prompt 29: alerts, last-known values, and runbook drills."""
from __future__ import annotations

from pathlib import Path

from app.services.ops_observe.otel import recorded_span_names, reset_spans
from app.services.ops_observe.otel import setup as setup_otel
from app.services.ops_observe.service import (
    admin_view,
    drill,
    log_event,
    note_failure,
    p95,
    read_degraded,
    record_error,
    record_latency,
    record_report_seconds,
    record_shadow_diff,
    remember,
    reset,
    slo_status,
    start_span,
)
from app.services.qa.feature_flags import is_enabled, reset_for_tests

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
_BOOKS = (
    "data-provider",
    "broker",
    "queue-overflow",
    "backup-restore",
    "release-rollback",
    "key-compromise",
)


def setup_function() -> None:
    reset_for_tests()
    reset()
    reset_spans()


def teardown_function() -> None:
    reset_for_tests()
    reset()


def test_flags_and_unset_price_stay() -> None:
    assert is_enabled("qa_ops_observe") is True
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_partners") is False


def test_empty_slo_is_unset_and_breach_alerts() -> None:
    assert p95([]) == "нет данных"
    status = slo_status()
    assert status["api"] == "нет данных"
    assert status["sync_timeout_seconds"] == "нет данных"
    assert status["availability"] == "нет данных"
    assert status["backup"] == "нет данных"
    assert status["infra_payment"] == "нет данных"
    record_latency(100)
    record_latency(200)
    record_latency(800)
    assert slo_status()["api"] == "breach"
    record_report_seconds(10)
    assert slo_status()["report"] == "ok"
    record_error("provider")
    record_shadow_diff()
    view = admin_view()
    assert view["shadow_diffs"] == "1"
    assert view["live"] is False
    assert view["partners"] is False
    assert view["infra_payment"] == "нет данных"


def test_provider_failure_keeps_last_value() -> None:
    remember("market_data", "100")
    fresh = read_degraded("market_data", failed=False)
    assert fresh["mark"] == "текущее"
    failed = read_degraded("market_data", failed=True)
    assert failed["value"] == "100"
    assert failed["mark"] == "последнее известное"
    assert failed["status"] == "degraded"
    unknown = read_degraded("broker", failed=True)
    assert unknown["value"] == "нет данных"
    alert = note_failure("market_data", "artificial")
    assert alert["name"] == "market_data.down"
    assert "market_data.down" in admin_view()["alerts"]


def test_log_keeps_request_id_and_drops_secrets() -> None:
    row = log_event("req-29", "read", token="hidden", symbol="SBER")
    assert row["request_id"] == "req-29"
    assert "token" not in row
    assert row["symbol"] == "SBER"
    assert start_span("report", "req-29").startswith("report:")


def test_every_runbook_drill_emits_an_alert() -> None:
    remember("market_data", "100")
    drilled = [drill(name) for name in _BOOKS]
    assert drilled[0]["alert"] == "market_data.down"
    assert drilled[0]["value"] == "100"
    assert drilled[0]["mark"] == "последнее известное"
    assert {row["runbook"] for row in drilled} == set(_BOOKS)
    assert all(row["alert"].endswith(".down") for row in drilled)


def test_otel_span_and_collector_config() -> None:
    setup_otel()
    start_span("report", "req-29")
    names = recorded_span_names()
    assert "report" in names
    view = admin_view()
    assert view["otel"]["sdk"] == "on"
    assert view["otel"]["exporter"] == "in_memory"
    assert "fastapi" in view["otel"]["instrumentation"]
    collector = Path(__file__).resolve().parents[3] / "infrastructure" / "monitoring" / "otel-collector.yaml"
    text = collector.read_text(encoding="utf-8")
    assert "otlp" in text
    assert "memory_limiter" in text


def test_ops_texts_omit_forbidden_phrases() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "app" / "services" / "ops_observe" / "service.py").read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN:
        assert phrase not in text
