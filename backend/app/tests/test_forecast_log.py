"""Prompt 11A: append-only forecast_log, settlement via official_close, immutability."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.forecast_log.record import (
    emit_from_chat_payload,
    emit_from_forecast_out,
    emit_from_market_payload,
    record_emission,
)
from app.services.forecast_log.settle import settle_due, settle_row
from app.services.forecast_log.store import ImmutableLogError, get_store
from app.services.forecast_log.summary import internal_summary
from app.services.market_data.eod import EodRow, MissingOfficialClose
from app.services.qa.feature_flags import reset_for_tests
from app.tests.qa_session import auth_headers
from app.tasks.celery_app import celery_app
from app.tasks.forecast_log import emit_forecast_log_basket_task


@pytest.fixture(autouse=True)
def _reset_log():
    reset_for_tests()
    get_store().reset()
    yield
    get_store().reset()
    reset_for_tests()


def _emit(**kwargs):
    base = dict(
        ticker="SBER",
        instrument_id="SBER",
        horizon_days=1,
        direction=1,
        probability="0.60",
        section="forecast",
        model_id="test",
        model_version="v1",
        issued_price="100",
        issued_price_source="test",
        issued_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    base.update(kwargs)
    return record_emission(**base)


def _eod(close: str = "110") -> EodRow:
    return EodRow(
        instrument_id="SBER",
        session_date=date(2024, 1, 2),
        official_close=Decimal(close),
        last_close=Decimal("999"),
        volume=Decimal("1"),
        source="iss_moex",
        board="TQBR",
        license_tag="internal_only",
        as_of=date(2024, 1, 2),
    )


def test_append_and_hash_chain():
    a = _emit()
    b = _emit(ticker="GAZP", instrument_id="GAZP")
    assert a.id == 1
    assert b.prev_hash == a.row_hash
    assert a.row_hash != b.row_hash


def test_update_and_delete_forbidden():
    _emit()
    with pytest.raises(ImmutableLogError):
        get_store().update(1, direction=-1)
    with pytest.raises(ImmutableLogError):
        get_store().delete(1)


def test_settle_uses_official_close_not_last():
    row = _emit()
    settled = settle_row(row.id, Decimal("100"), 1, _eod("110"))
    assert settled.actual_price == "110"
    assert settled.actual_source == "official_close"
    assert settled.direction_correct is True
    missing = EodRow(
        instrument_id="SBER",
        session_date=date(2024, 1, 2),
        official_close=None,
        last_close=Decimal("999"),
        volume=None,
        source="iss_moex",
        board="TQBR",
        license_tag="internal_only",
        as_of=date(2024, 1, 2),
    )
    with pytest.raises(MissingOfficialClose):
        settle_row(row.id, Decimal("100"), 1, missing)


def test_correction_appends_new_settlement():
    row = _emit()
    first = settle_row(row.id, Decimal("100"), 1, _eod("110"))
    second = settle_row(row.id, Decimal("100"), 1, _eod("90"), correction_of=first.id)
    assert second.id != first.id
    assert second.correction_of == first.id
    assert second.direction_correct is False
    assert len(get_store().settlements()) == 2


def test_summary_vs_naive():
    row = _emit()
    settle_row(row.id, Decimal("100"), 1, _eod("110"))
    summary = internal_summary()
    assert summary["emissions"] == 1
    assert summary["public"] is False
    h = summary["horizons"][0]
    assert h["hits"] == 1
    assert h["beats_naive"] is True


def test_emit_from_surfaces():
    assert emit_from_forecast_out(
        {"symbol": "AAPL", "instrument_id": 1, "confidence": 0.7, "action_recommendation": "buy"},
        section="forecast",
    )
    assert emit_from_chat_payload({"ticker": "MSFT", "expected_return_sign": 1, "calibrated_confidence": 0.55})
    assert emit_from_market_payload({"dominant_regime": "risk_on", "confidence": 0.4})
    sections = {r.section for r in get_store().rows()}
    assert sections == {"forecast", "ai_chat", "market_analysis"}


def test_basket_task_and_beat():
    result = emit_forecast_log_basket_task()
    assert result["saved"] == 0
    assert result["reason"] == "нет цены"
    assert get_store().rows() == []
    assert "emit-forecast-log-basket-daily" in celery_app.conf.beat_schedule
    assert "settle-forecast-log-daily" in celery_app.conf.beat_schedule
    assert "snapshot-forecast-log-daily" in celery_app.conf.beat_schedule


def test_daily_snapshot_hash():
    _emit()
    digest = get_store().daily_snapshot(date(2024, 1, 2))
    assert len(digest) == 64
    assert get_store().snapshots()["2024-01-02"] == digest


def test_settle_due_skips_open_horizon():
    _emit(horizon_days=365, issued_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert settle_due({"SBER": _eod()}, as_of=date(2024, 1, 2)) == []


def test_summary_api():
    _emit()
    client = TestClient(app)
    anon = client.get("/api/v1/forecast-log/summary")
    assert anon.status_code == 401
    res = client.get("/api/v1/forecast-log/summary", headers=auth_headers("u1"))
    assert res.status_code == 200
    assert res.json()["emissions"] >= 1
    assert "public" not in res.json()


def test_migration_revokes_update():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0055_forecast_log.py").read_text(
        encoding="utf-8"
    )
    assert "REVOKE UPDATE, DELETE ON forecast_log" in text
    assert "forecast_log_settlement" in text
