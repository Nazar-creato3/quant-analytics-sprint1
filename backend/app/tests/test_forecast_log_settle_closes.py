"""GA16-269: settlement uses official closes, never an empty price map."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.market_data.eod import EodRow
from app.tasks.forecast_log import settle_forecast_log_task


def test_empty_close_map_is_not_a_settlement(monkeypatch) -> None:
    calls: list[dict] = []

    def capture(closes: dict) -> list:
        calls.append(closes)
        return []

    monkeypatch.setattr("app.services.forecast_log.settle.settle_due", capture)
    result = settle_forecast_log_task()
    assert calls == []
    assert result["settled"] == 0
    assert result["reason"] == "нет данных"


def test_settlement_receives_the_official_close(monkeypatch) -> None:
    row = EodRow(
        instrument_id="SBER",
        session_date=date(2026, 10, 16),
        official_close=Decimal("250"),
        last_close=Decimal("249"),
        volume=Decimal("1"),
        source="book",
        board=None,
        license_tag="official",
        as_of=date(2026, 10, 16),
    )
    seen: list[dict] = []

    def capture(closes: dict) -> list:
        seen.append(closes)
        return ["row"]

    monkeypatch.setattr("app.services.forecast_log.settle.official_closes", lambda: {"SBER": row})
    monkeypatch.setattr("app.services.forecast_log.settle.settle_due", capture)
    result = settle_forecast_log_task()
    assert seen == [{"SBER": row}]
    assert result["settled"] == 1
    assert seen[0]["SBER"].official_close == Decimal("250")
