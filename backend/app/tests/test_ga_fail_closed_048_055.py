"""GA-048…055: pretrade, live_hooks, bots book, robot kill fail closed."""
from __future__ import annotations

from pathlib import Path

import pytest
from datetime import datetime, timezone

from app.services.ops_desk.live_hooks import halt_reason, reject_new_order
from app.services.pretrade.policy import evaluate
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()


def teardown_function() -> None:
    reset_for_tests()


def test_ga048_regime_exception_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("regime down")

    monkeypatch.setattr("app.services.market_regime.service.classify_ticker", boom)
    human = evaluate(
        kind="manual_order",
        actor="human",
        user_id="ga048",
        ticker="SBER",
        qty=1,
        price=10,
        nav=10_000,
    )
    assert human.verdict == "block"
    assert any(r.code == "regime_unavailable" for r in human.reasons)


def test_ga049_publish_failure_does_not_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("bus down")

    monkeypatch.setattr("app.services.pretrade.policy.publish_event", boom)
    auto = evaluate(
        kind="bot",
        actor="auto",
        user_id="ga049",
        ticker="SBER",
        qty=4000,
        price=30,
        nav=10_000,
    )
    assert auto.verdict == "block"


def test_ga050_missing_price_blocks_human() -> None:
    human = evaluate(
        kind="manual_order",
        actor="human",
        user_id="ga050",
        ticker="SBER",
        qty=1,
        price=0,
        nav=10_000,
        confirmed=True,
    )
    assert human.verdict == "block"
    assert any(r.code == "no_price" for r in human.reasons)


def test_ga051_reject_order_missing_price() -> None:
    msg = reject_new_order(
        ticker="AAA",
        side="buy",
        qty=1.0,
        price=0.0,
        settings_cap=250,
        account_total=250,
        sensors={"day_pnl_frac": 0.0, "dd_frac": 0.0, "last_bar": None, "broker_connected": True},
    )
    assert msg == "нет данных"


def test_ga052_reject_order_missing_pnl_sensors() -> None:
    msg = reject_new_order(
        ticker="AAA",
        side="buy",
        qty=1.0,
        price=10.0,
        settings_cap=250,
        account_total=250,
        sensors={"last_bar": None, "broker_connected": True},
    )
    assert msg == "нет данных: pnl snapshot missing"


def test_ga053_halt_reason_none_pnl_refuses() -> None:
    assert halt_reason({}) == "pnl_unavailable"
    fresh = datetime.now(timezone.utc)
    assert halt_reason({"day_pnl_frac": 0.0, "dd_frac": 0.0, "last_bar": fresh, "broker_connected": True}) is None
    # no bar at all is not "healthy" any more (GA16-007): the kill trips
    assert halt_reason({"day_pnl_frac": 0.0, "dd_frac": 0.0}) == "data_stale"


def test_ga054_bots_book_except_logs_not_pass() -> None:
    from app.services.bots import common as common_mod
    import inspect

    src = inspect.getsource(common_mod.record_paper_trade)
    assert "except Exception:\n        pass" not in src
    assert "portfolio_book bot trade skipped" in src


def test_ga055_profile_exception_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("ips down")

    monkeypatch.setattr("app.services.investment_profile.service.get_profile", boom)
    auto = evaluate(
        kind="bot",
        actor="auto",
        user_id="ga055",
        ticker="SBER",
        qty=1,
        price=10,
        nav=10_000,
    )
    assert auto.verdict == "block"
    assert any(r.code == "profile_unavailable" for r in auto.reasons)


def test_ga_robot_ops_halt_except_trips() -> None:
    from app.services.robot import risk as risk_mod
    import inspect

    src = inspect.getsource(risk_mod.check_portfolio_kill_switch)
    assert 'reason = "ops:unavailable"' in src
    assert "except Exception:\n        pass" not in src


def test_letter_zh_pnl_snapshot_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ops_desk.live_hooks import PnlSnapshotUnavailable, read_pnl_snapshot

    missing = tmp_path / "missing.json"
    monkeypatch.setattr("app.services.ops_desk.live_hooks._pnl_path", lambda: missing)
    with pytest.raises(PnlSnapshotUnavailable):
        read_pnl_snapshot(dest=missing)
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not-json", encoding="utf-8")
    with pytest.raises(PnlSnapshotUnavailable):
        read_pnl_snapshot(dest=corrupt)
    stale = tmp_path / "stale.json"
    stale.write_text(
        '{"ts": "2000-01-01T00:00:00+00:00", "day_pnl_frac": 0.01, "dd_frac": 0.01}',
        encoding="utf-8",
    )
    with pytest.raises(PnlSnapshotUnavailable):
        read_pnl_snapshot(dest=stale, max_age_hours=0.0)
    msg = reject_new_order(
        ticker="SBER",
        side="buy",
        qty=1.0,
        price=10.0,
        settings_cap=250,
        account_total=250,
        sensors=None,
        user_id="ga-zh",
    )
    assert msg is not None
    blob = str(msg).lower()
    assert ("pnl" in blob) or ("нет данных" in str(msg))
