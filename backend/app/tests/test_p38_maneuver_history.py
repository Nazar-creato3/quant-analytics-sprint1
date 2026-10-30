"""Prompt 38 walk-forward. Does not import app.main."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np

from app.services.explanations.service import FORBIDDEN
from app.services.maneuver_history.directory import (
    DirectoryName,
    is_tradable,
    load_delist_notes,
    retain_names,
)
from app.services.maneuver_history.execute import (
    fill_at_next_session,
    open_ledger,
    tax_summary,
)
from app.services.maneuver_history.handoff import (
    control_document,
    read_control_input,
    write_control_input,
)
from app.services.maneuver_history.paths import control_path
from app.services.maneuver_history.pit import (
    business_sessions,
    detect_leak,
    quarter_decision_indexes,
    returns_through,
    slice_dates,
)
from app.services.maneuver_history.report import render_validation
from app.services.maneuver_history.scenarios import (
    SESSION_COUNT,
    START,
    crisis_window_status,
)
from app.services.maneuver_history.simulate import run_validation
from app.services.maneuver_history.stats import (
    block_bootstrap_interval,
    cscv_probability,
    deflated_sharpe_ratio,
    period_sharpe,
)
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global

PACKAGE = Path(__file__).resolve().parents[1] / "services" / "maneuver_history"


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()


def teardown_function() -> None:
    reset_for_tests()
    get_book().reset()


def test_package_does_not_import_app_main() -> None:
    for path in PACKAGE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "app.main" not in text


def test_directory_keeps_unknown_and_delisted_names() -> None:
    gone = DirectoryName("GONE", date(2020, 1, 1), "2020-01-01")
    unknown = DirectoryName("LIVE", None, "")
    kept = retain_names([gone, unknown], as_of=date(2024, 6, 1))
    assert [name.ticker for name in kept] == ["GONE", "LIVE"]
    assert kept[1].delist_note == "нет данных"
    assert is_tradable(gone, date(2024, 6, 1)) is False
    assert is_tradable(unknown, date(2024, 6, 1)) is True
    notes = load_delist_notes(["GONE", "LIVE"], path=Path("docs/qa/delistings-absent.json"))
    assert notes == {"GONE": "нет данных", "LIVE": "нет данных"}


def test_injected_future_date_is_detected() -> None:
    as_of = date(2024, 4, 1)
    history = [date(2024, 3, 29), as_of, date(2024, 4, 2)]
    assert detect_leak(as_of, history) is True
    assert detect_leak(as_of, slice_dates(history, as_of)) is False
    prices = [Decimal("100"), Decimal("110"), Decimal("1000000")]
    assert returns_through(prices, 1) == returns_through(prices[:2], 1)
    assert len(returns_through(prices, 1)) == 1
    assert Decimal("1000000") not in [Decimal(str(item)) for item in returns_through(prices, 1)]


def test_next_session_fill_reports_tax_base_without_cash_tax() -> None:
    ledger = open_ledger({"SBER": Decimal("1")}, {"SBER": Decimal("100")}, date(2024, 1, 1))
    fill = fill_at_next_session(
        fill_on=date(2024, 1, 2),
        prices={"SBER": Decimal("110")},
        orders=[{"ticker": "SBER", "side": "sell", "qty": "1"}],
        ledger=ledger,
    )
    tax = tax_summary(ledger.realized, year=2024)
    assert tax["tax_base"] == "10.00"
    assert tax["tax_cash"] is None
    assert tax["tax_cash_computed"] is False
    assert fill["costs_status"] == "нет данных"
    assert ledger.wealth({"SBER": Decimal("110")}) == Decimal("110")


def test_crisis_windows_and_two_quarter_dates() -> None:
    days = business_sessions(START, SESSION_COUNT)
    indexes = quarter_decision_indexes(days)
    assert len(indexes) == 2
    assert days[indexes[0]] == date(2024, 1, 1)
    assert days[indexes[1]] == date(2024, 4, 1)
    assert indexes[-1] < len(days) - 1
    assert set(crisis_window_status()) == {"2008", "2014", "2020", "2022"}
    assert all(status == "нет данных" for status in crisis_window_status().values())


def test_statistics_selection_penalty_and_cscv() -> None:
    steady = cscv_probability([[0.01] * 32, [0.02] * 32])
    assert steady["status"] == "ok"
    assert Decimal(str(steady["pbo"])) == 0
    overfit = [1.0] * 16 + [-1.0] * 16
    dirty = cscv_probability([overfit, [0.05] * 32])
    assert dirty["status"] == "ok"
    assert Decimal(str(dirty["pbo"])) > 0
    returns = [0.01, -0.004, 0.008, 0.002, -0.003, 0.006, 0.001, 0.004] * 5
    sharpe = period_sharpe(np.asarray(returns, dtype=float))
    assert sharpe is not None
    base = deflated_sharpe_ratio(returns, [sharpe, sharpe])
    wide = deflated_sharpe_ratio(returns, [sharpe - 1.0, sharpe, sharpe + 1.0])
    assert base["status"] == "ok"
    assert wide["status"] == "ok"
    assert Decimal(str(wide["dsr"])) < Decimal(str(base["dsr"]))
    interval = block_bootstrap_interval(returns, seed=38, kind="mean", n_boot=40)
    assert interval["status"] == "ok"
    assert Decimal(str(interval["low"])) <= Decimal(str(interval["high"]))


def test_seeded_walk_repeats_and_hides_future_bars(tmp_path: Path) -> None:
    kwargs = dict(
        seed=38,
        start=date(2024, 3, 1),
        sessions=30,
        portfolio_ids=["p2_three_cashflows"],
        profile_names=["moderate"],
        write=False,
        include_parameter_grid=True,
    )
    first = run_validation(**kwargs)
    second = run_validation(**kwargs)
    first.pop("elapsed_sec")
    second.pop("elapsed_sec")
    assert first == second
    assert first["leak_failures"] == 0
    assert first["point_in_time_ok"] is True
    assert first["crisis_windows"]["2020"] == "нет данных"
    assert first["decision_dates"] == ["2024-04-01"]
    scenario = first["scenarios"][0]
    assert scenario["directory_dropped"] == 0
    assert {row["ticker"] for row in scenario["directory"]} == {"A", "B", "C"}
    assert all(row["delist_note"] == "нет данных" and row["retained"] for row in scenario["directory"])
    assert list(scenario["strategies"]) == [
        "do_nothing",
        "quarterly_equal_weight",
        "target_no_views",
        "maneuvers",
    ]
    assert first["target_sources_seen"] == ["user"]
    for block in scenario["strategies"].values():
        metrics = block["metrics"]
        assert metrics["tax_cash"] is None
        assert metrics["tax_cash_computed"] is False
        if int(metrics["trades"]) > 0:
            assert metrics["return_after_costs_status"] == "нет данных"
        else:
            assert metrics["return_after_costs"] == metrics["return_before_costs"]
    idle = scenario["strategies"]["do_nothing"]["metrics"]
    assert idle["return_after_costs_status"] == "ok"
    assert idle["maneuver_frequency"] == "0.00000000"
    selection = first["parameter_selection"]
    assert selection["status"] == "ok"
    assert selection["headline_method"] == "mean_variance"
    assert selection["headline_not_replaced"] is True
    text = render_validation(first)
    lowered = text.lower()
    for word in FORBIDDEN:
        assert word not in lowered
    report = tmp_path / "report.md"
    control = tmp_path / "control.json"
    written = run_validation(
        **{**kwargs, "write": True, "report_file": report, "control_file": control}
    )
    written.pop("elapsed_sec")
    assert written == first
    loaded = read_control_input(control)
    assert loaded["schema"] == "maneuver_history.control.v1"
    assert loaded["for_prompt"] == 40
    assert loaded == control_document(written)


def test_history_flag_off_does_not_simulate() -> None:
    set_global("qa_maneuver_history", False)
    result = run_validation(seed=38, sessions=5, include_parameter_grid=False)
    assert result["status"] == "off"


def test_published_control_matches_fresh_run() -> None:
    published = read_control_input(control_path())
    fresh = run_validation(seed=38, write=False)
    assert control_document(fresh) == published
