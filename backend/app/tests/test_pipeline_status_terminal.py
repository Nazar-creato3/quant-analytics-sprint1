"""Pipeline status helpers."""
from __future__ import annotations

from app.api.v1.endpoints.pipeline import (
    _celery_result_payload,
    _pipeline_failure_from_payload,
)


def test_celery_result_payload_dict():
    assert _celery_result_payload({"status": "halted"}) == {"status": "halted"}


def test_celery_result_payload_non_dict():
    assert _celery_result_payload("oops") == {}


def test_pipeline_failure_from_halted():
    msg = _pipeline_failure_from_payload({"status": "halted", "reason": "kill_switch"})
    assert msg == "kill_switch"


def test_pipeline_failure_from_success_payload():
    assert _pipeline_failure_from_payload({"status": "complete", "report_id": "r1"}) is None
