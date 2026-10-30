"""GA16-280: 1/3/6 month outcomes must not share one today's amount."""
from __future__ import annotations

from datetime import date

import pytest

from app.services.decision_core.journal import add_months, record_shown, reset_for_tests, settle


def setup_function() -> None:
    reset_for_tests()


def test_each_due_horizon_is_priced_on_its_due_date(monkeypatch: pytest.MonkeyPatch) -> None:
    shown_on = date(2026, 1, 15)
    record_shown(
        "u-horizons",
        [
            {
                "signal_id": "d59.total_rubles",
                "module": "decisions_report",
                "source": "decisions_report.analyze_decisions",
                "figure": "10.00",
            }
        ],
        as_of=shown_on,
    )
    priced: list[date] = []

    def _price(*, user_id: str, mode: str, date_to: date | None = None, **_kwargs: object) -> dict:
        del user_id, mode
        assert date_to is not None
        priced.append(date_to)
        return {"total_rubles": f"{date_to.month * 10}.00"}

    monkeypatch.setattr("app.services.decisions_report.service.analyze_decisions", _price)
    out = settle("u-horizons", as_of=add_months(shown_on, 6))
    outcomes = out[0]["outcomes"]
    assert outcomes["m1"]["priced_on"] == add_months(shown_on, 1).isoformat()
    assert outcomes["m3"]["priced_on"] == add_months(shown_on, 3).isoformat()
    assert outcomes["m6"]["priced_on"] == add_months(shown_on, 6).isoformat()
    assert outcomes["m1"]["total_rubles"] != outcomes["m3"]["total_rubles"]
    assert outcomes["m3"]["total_rubles"] != outcomes["m6"]["total_rubles"]
    assert priced == [add_months(shown_on, 1), add_months(shown_on, 3), add_months(shown_on, 6)]
