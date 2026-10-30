"""GA16-284: goal amount from decision sources is Decimal, not float."""
from __future__ import annotations

from decimal import Decimal

from app.services.decision_core.sources import _k5


def test_k5_passes_decimal_not_float(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def capture(user_id: str, *, target_amount, target_date: str, mode: str = "paper"):
        seen["target_amount"] = target_amount
        seen["type"] = type(target_amount)
        return {"data_status": "ok", "target_amount": format(Decimal(str(target_amount)), "f")}

    monkeypatch.setattr("app.services.goals.service.explain_goal", capture)
    out = _k5("u1", "paper", "p1", {"goal_amount": "100000.50", "goal_date": "2027-01-01"})
    assert seen["type"] is Decimal
    assert seen["target_amount"] == Decimal("100000.50")
    assert out["target_amount"] == "100000.50"


def test_k5_rejects_bad_amount() -> None:
    out = _k5("u1", "paper", "p1", {"goal_amount": "не число", "goal_date": "2027-01-01"})
    assert out["data_status"] == "нет данных"
