"""Tests for public anonymized track record endpoint."""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.track_record import router as track_record_router
from app.services.track_record.types import PublicTrackRecordSummary


def _forbidden_keys() -> frozenset[str]:
    return PublicTrackRecordSummary(
        generated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        period_days=90,
        benchmark_count=1,
        total_validation_points=10,
        aggregate_calibration_error=0.1,
        aggregate_brier_score=0.2,
        level_accuracy=(),
        regime_accuracy=(),
        low_confidence_regimes=(),
        summary="test",
    ).forbidden_response_keys


def test_public_track_record_has_no_client_identifiers():
    app = FastAPI()
    app.include_router(track_record_router, prefix="/api/v1")
    client = TestClient(app)

    response = client.get("/api/v1/track-record/public")
    assert response.status_code == 200

    payload = response.json()
    serialized = json.dumps(payload).lower()
    for key in _forbidden_keys():
        assert key not in payload
        assert f'"{key}"' not in serialized

    assert payload["benchmark_count"] >= 1
    assert payload["total_validation_points"] > 0
    assert "disclaimer" in payload
    assert "level_accuracy" in payload
    assert "regime_accuracy" in payload


def test_track_record_service_summary():
    from app.services.track_record.service import TrackRecordService

    summary = TrackRecordService().get_public_summary()
    assert summary.total_validation_points > 0
    assert summary.aggregate_calibration_error >= 0.0
    assert summary.benchmark_count == 3
