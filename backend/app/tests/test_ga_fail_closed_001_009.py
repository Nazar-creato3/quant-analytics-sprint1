"""GA-001…GA-009: act_desk and execution guard refuse instead of swallowing."""
from __future__ import annotations

import pytest

from app.services.act_desk.service import preview_orders, reset
from app.services.execution.adapter import OrderRequest, _guard_broker_submission
from app.services.execution.guard import ManeuverExecutionContext
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()
    reset()


def teardown_function() -> None:
    reset()
    reset_for_tests()


def test_ga005_006_preview_refuses_missing_qty_price() -> None:
    with pytest.raises(ValueError) as empty:
        preview_orders(user_id="u", orders=[])
    assert "нет данных" in str(empty.value)
    with pytest.raises(ValueError) as no_qty:
        preview_orders(user_id="u", orders=[{"ticker": "SBER", "qty": "", "price": "100"}])
    assert "нет данных" in str(no_qty.value)
    with pytest.raises(ValueError) as no_px:
        preview_orders(user_id="u", orders=[{"ticker": "SBER", "qty": "1", "price": ""}])
    assert "нет данных" in str(no_px.value)


def test_ga009_guard_refuses_when_live_hooks_break(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kwargs):  # noqa: ANN003
        raise RuntimeError("sensor down")

    monkeypatch.setattr("app.services.ops_desk.live_hooks.reject_new_order", boom)
    req = OrderRequest(
        ticker="SBER",
        side="buy",
        qty=1.0,
        order_type="limit",
        limit_price=100.0,
        maneuver_context=ManeuverExecutionContext(maneuver_id="m1", status="approved"),
    )
    with pytest.raises(RuntimeError) as err:
        _guard_broker_submission(req)
    assert "live order guard failed" in str(err.value)


def test_ga009_guard_refuses_missing_price() -> None:
    req = OrderRequest(
        ticker="SBER",
        side="buy",
        qty=1.0,
        order_type="market",
        maneuver_context=ManeuverExecutionContext(maneuver_id="m1", status="approved"),
    )
    with pytest.raises(ValueError) as err:
        _guard_broker_submission(req)
    assert "нет данных" in str(err.value)
