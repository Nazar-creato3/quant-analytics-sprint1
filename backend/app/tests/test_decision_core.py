import time
from datetime import date

import pytest

from app.services.decision_core.calibrate import (
    configure_min_obs,
    live_weights,
    reset_min_obs,
)
from app.services.decision_core.journal import (
    add_months,
    record_action,
    record_shown,
    reset_for_tests,
    settle,
)
from app.services.decision_core.map import from_risk
from app.services.decision_core.service import collect_signals
from app.services.decision_core.sources import default_sources
from app.services.explanations.service import filter_wording
from app.services.qa import feature_flags


def setup_function() -> None:
    feature_flags.reset_for_tests()
    feature_flags.set_global("qa_decision_core", True)
    reset_for_tests()
    reset_min_obs()


def _source(payload):
    def _fn(user_id: str, mode: str, portfolio_id: str, extra: dict) -> dict:
        del user_id, mode, portfolio_id, extra
        return payload

    return _fn


def _sources() -> dict:
    base = {key: _source({"data_status": "нет данных"}) for key in default_sources()}
    base["risk"] = _source({"data_status": "ok", "var_95": 0.2, "as_of": "2026-10-15"})
    base["d62"] = _source({"data_status": "ok", "total_rubles": "100000.00", "as_of": "2026-10-15"})
    base["k1"] = _source(
        {"data_status": "ok", "alternatives": [{"diff_twr_pp": "2.0000"}], "as_of": "2026-10-15"}
    )
    return base


def test_rank_uses_source_figures() -> None:
    out = collect_signals(user_id="u1", sources=_sources(), record=False)
    assert [row["signal_id"] for row in out["signals"]] == [
        "risk.var95",
        "d62.total_rubles",
        "k1.diff_twr_pp",
    ]
    assert out["signals"][0]["figure"] == "0.2"
    assert out["screen"][0]["why"].startswith("Нашёл модуль риск")
    assert filter_wording(out["signals"][0]["why"]) == []
    assert filter_wording(out["signals"][0]["if_idle"]) == []
    assert "купите" not in out["caption"]
    assert out["shadow_weights"]["changes_rank"] is False
    assert out["weights_live"] is False


def test_one_source_failure_keeps_the_rest() -> None:
    sources = _sources()

    def _boom(user_id: str, mode: str, portfolio_id: str, extra: dict) -> dict:
        del user_id, mode, portfolio_id, extra
        raise RuntimeError("down")

    sources["k6"] = _boom
    out = collect_signals(user_id="u1", sources=sources, record=False)
    assert any(row["module"] == "k6" and row["reason"] == "нет данных" for row in out["missing"])
    assert out["signals"][0]["signal_id"] == "risk.var95"


def test_slow_source_is_skipped() -> None:
    sources = _sources()

    def _slow(user_id: str, mode: str, portfolio_id: str, extra: dict) -> dict:
        del user_id, mode, portfolio_id, extra
        time.sleep(1.5)
        return {"data_status": "ok", "var_95": 0.9}

    sources["risk"] = _slow
    out = collect_signals(user_id="u1", sources=sources, record=False, timeout_s=0.2)
    assert all(row["signal_id"] != "risk.var95" for row in out["signals"])
    assert any(row["module"] == "risk" for row in out["missing"])
    assert any(row["signal_id"] == "d62.total_rubles" for row in out["signals"])


def test_flag_off_returns_empty() -> None:
    feature_flags.set_global("qa_decision_core", False)
    out = collect_signals(user_id="u1", sources=_sources(), record=False)
    assert out["signals"] == []
    assert out["reason"] == "qa_decision_core off"


def test_decision_core_flag_default_is_off() -> None:
    feature_flags.reset_for_tests()
    assert feature_flags.is_enabled("qa_decision_core") is False
    out = collect_signals(user_id="u1", sources=_sources(), record=False)
    assert out["signals"] == []
    assert out["reason"] == "qa_decision_core off"


def test_no_figure_is_not_a_zero() -> None:
    assert from_risk({"data_status": "нет данных", "var_95": None}) is None
    assert from_risk({"data_status": "ok", "var_95": None}) is None


def test_sources_cover_the_module_list() -> None:
    assert set(default_sources()) == {
        "risk",
        "k6",
        "k1",
        "d59",
        "d62",
        "d60",
        "d56",
        "d57",
        "d64",
        "d61",
        "k3",
        "d65",
        "d63",
        "d58a",
        "d58b",
        "k5",
    }


def test_journal_waits_for_horizons(monkeypatch: pytest.MonkeyPatch) -> None:
    shown = record_shown(
        "u1",
        [
            {
                "signal_id": "d59.total_rubles",
                "module": "decisions_report",
                "source": "decisions_report.analyze_decisions",
                "figure": "10.00",
            }
        ],
        as_of=date(2026, 1, 15),
    )
    record_action("u1", shown[0]["id"], "opened")
    early = settle("u1", as_of=date(2026, 1, 20))
    assert early[0]["outcomes"]["m1"]["reason"] == "срок не наступил"
    assert early[0]["outcomes"]["m1"]["total_rubles"] is None

    def _price(*, user_id: str, mode: str, date_to: date | None = None, **_kwargs: object) -> dict:
        del user_id, mode
        return {"data_status": "ok", "total_rubles": "42.00", "as_of": (date_to or date.today()).isoformat()}

    monkeypatch.setattr("app.services.decisions_report.service.analyze_decisions", _price)
    due = settle("u1", as_of=add_months(date(2026, 1, 15), 1))
    assert due[0]["outcomes"]["m1"]["total_rubles"] == "42.00"
    assert due[0]["outcomes"]["m1"]["source"] == "decisions_report.analyze_decisions"
    assert due[0]["outcomes"]["m3"]["reason"] == "срок не наступил"


def test_shadow_weight_does_not_change_order(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_min_obs(1)
    shown = record_shown(
        "u1",
        [
            {
                "signal_id": "risk.var95",
                "module": "risk_engine",
                "source": "risk_engine.compute_risk_for_user",
                "figure": "0.2",
            },
            {
                "signal_id": "d62.total_rubles",
                "module": "total_costs",
                "source": "total_costs.analyze_costs",
                "figure": "100000.00",
            },
        ],
        as_of=date(2026, 1, 15),
    )
    record_action("u1", shown[0]["id"], "dismissed")
    record_action("u1", shown[1]["id"], "noted")

    def _price(*, user_id: str, mode: str, date_to: date | None = None, **_kwargs: object) -> dict:
        del user_id, mode, date_to
        return {"data_status": "ok", "total_rubles": "1.00"}

    monkeypatch.setattr("app.services.decisions_report.service.analyze_decisions", _price)
    settle("u1", as_of=add_months(date(2026, 1, 15), 1))
    base = collect_signals(user_id="u1", sources=_sources(), as_of=date(2026, 1, 15), record=False)
    assert [row["signal_id"] for row in base["signals"][:2]] == ["risk.var95", "d62.total_rubles"]
    assert base["shadow_weights"]["weights"]["d62.total_rubles"]["weight"] > 1
    assert base["weights_live"] is False
    feature_flags.set_global("qa_brain_weights_live", True)
    still = collect_signals(user_id="u1", sources=_sources(), as_of=date(2026, 1, 15), record=False)
    assert still["signals"][0]["signal_id"] == "risk.var95"
    from app.services.decision_core.journal import mark_founder_reviewed

    mark_founder_reviewed()
    live = collect_signals(user_id="u1", sources=_sources(), as_of=date(2026, 1, 15), record=False)
    assert live["weights_live"] is True
    assert live["signals"][0]["signal_id"] == "d62.total_rubles"
    assert live_weights("u1")["risk.var95"] < 1


def test_calibration_empty_and_corrupt_counts_are_finite(monkeypatch: pytest.MonkeyPatch) -> None:
    import math

    from app.services.decision_core.calibrate import proposed_weights

    assert proposed_weights("nobody") == {}
    monkeypatch.setattr(
        "app.services.decision_core.calibrate.observations",
        lambda _uid: {"x.edge": {"success": -2, "failure": 0}},
    )
    row = proposed_weights("u1")["x.edge"]
    assert math.isfinite(row["posterior"])
    assert math.isfinite(row["weight"])
    assert row["n"] == 0
    assert row["posterior"] == 0.5
