"""GA16-286: do not attribute returns to the last N business days."""
from __future__ import annotations

from app.services.fund_report.metrics import fund_metrics


def test_without_dates_no_invented_monthly_calendar() -> None:
    out = fund_metrics([0.01, -0.02, 0.015, 0.0, 0.005] * 20)
    assert out["data_status"] == "ok"
    assert out["monthly"] == []
    assert out.get("monthly_status") == "нет дат ряда"
    assert out["cagr"] is not None
    assert out["max_dd"] is not None


def test_with_dates_builds_monthly() -> None:
    rets = [0.01, -0.01, 0.02]
    dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
    out = fund_metrics(rets, dates=dates)
    assert out["data_status"] == "ok"
    assert out["monthly"]  # real calendar months only
