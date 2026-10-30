"""Portfolio risk analytics — historical VaR, attribution, correlation, stress."""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path

import numpy as np
import pytest

from app.schemas.portfolio_risk import PortfolioRiskAnalyticsOut
from app.services.portfolio.risk_analytics_math import (
    HoldingSpec,
    STRESS_SCENARIOS,
    build_report,
    fhs_var_triple,
    simple_returns,
)
from app.services.risk.portfolio_math.var import historical_var_es
from app.services.risk_engine.fhs import fhs_var_es


def test_crisis_labels_have_no_english() -> None:
    blob = " ".join(
        row["label_ru"] + " " + row["description_ru"] for row in STRESS_SCENARIOS.values()
    )
    assert "COVID" not in blob
    assert "to-trough" not in blob
    catalog = json.loads(
        Path(__file__).resolve().parents[1].joinpath("services/stress_library/scenarios.json").read_text(encoding="utf-8")
    )
    titles = " ".join(item["title"] for group in catalog.values() if isinstance(group, list) for item in group)
    assert "COVID" not in titles
    assert "carry" not in titles.lower()


def _tech_heavy_series() -> dict[str, list[tuple[str, float]]]:
    """Four names that share a common factor — мнимая диверсификация."""
    rng = np.random.default_rng(7)
    start = date(2019, 6, 1)
    end = date(2022, 12, 31)
    days: list[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    n = len(days) - 1
    common = rng.normal(0.0003, 0.011, size=n)
    crash = np.zeros(n)
    for i, d in enumerate(days[1:]):
        key = d.isoformat()
        if "2020-02-19" <= key <= "2020-03-23":
            crash[i] = -0.028
        elif "2022-01-03" <= key <= "2022-10-12":
            crash[i] = -0.0025

    def path(beta: float, idio: float, p0: float) -> list[tuple[str, float]]:
        rets = beta * common + crash + rng.normal(0.0, idio, size=n)
        price = p0
        rows = [(days[0].isoformat(), price)]
        for i, r in enumerate(rets):
            price = max(0.01, price * (1.0 + float(r)))
            rows.append((days[i + 1].isoformat(), price))
        return rows

    return {
        "SPY": path(1.00, 0.004, 300.0),
        "AAPL": path(1.15, 0.006, 150.0),
        "MSFT": path(1.10, 0.005, 220.0),
        "NVDA": path(1.35, 0.010, 80.0),
        "QQQ": path(1.20, 0.005, 280.0),
    }


def test_fhs_var_not_parametric_and_positive_loss():
    rng = np.random.default_rng(1)
    rets = np.concatenate([rng.normal(0.001, 0.01, 240), np.array([-0.08, -0.06, -0.05])])
    var95, var99, es95 = fhs_var_triple(rets)
    assert var95 is not None and var99 is not None and es95 is not None
    assert var95 > 0 and var99 > var95
    assert es95 >= var95


def test_empty_book_is_insufficient_not_fabricated():
    report = build_report(holdings=[], series_by_symbol={})
    assert report.insufficient_data is True
    assert report.var_95 is None
    assert "Открытых позиций нет" in report.notes[0]


def test_real_multi_position_var_factor_correlation_and_stress():
    series = _tech_heavy_series()
    holdings = [
        HoldingSpec("AAPL", 40_000, "technology"),
        HoldingSpec("MSFT", 30_000, "technology"),
        HoldingSpec("NVDA", 20_000, "technology"),
        HoldingSpec("QQQ", 10_000, "indices"),
    ]
    report = build_report(
        holdings=holdings,
        series_by_symbol=series,
        benchmark_symbol="SPY",
        lookback_days=252,
    )
    payload = report.to_dict()
    parsed = PortfolioRiskAnalyticsOut.model_validate(payload)

    assert parsed.insufficient_data is False
    assert parsed.var_95 is not None and parsed.var_95 > 0
    assert parsed.var_99 is not None and parsed.var_99 >= parsed.var_95
    assert parsed.var_95_usd is not None and parsed.var_95_usd > 0
    assert parsed.observations >= 40
    assert parsed.methodology["method"] == "fhs_ewma"
    assert parsed.methodology["rejected_method"] == "parametric_normal"
    assert parsed.lookback_start
    assert parsed.lookback_end
    assert "fhs" not in parsed.methodology["method_ru"].lower()
    assert "risk" not in parsed.methodology["method_ru"].lower()
    assert "equivalent_library" not in parsed.methodology

    # Sector MVP + concentration honesty
    assert parsed.sector_weights["technology"] >= 0.8
    assert {h.sector for h in parsed.holdings} <= {"технологии", "индексы", "нет данных"}
    assert "technology" not in {h.sector for h in parsed.holdings}
    assert "technology" not in (parsed.concentration_flag_ru or "")
    assert parsed.avg_pairwise_correlation is not None
    assert parsed.avg_pairwise_correlation > 0.5
    assert parsed.concentration_flag_ru
    assert "диверсификац" in parsed.concentration_flag_ru.lower()
    assert "technology" not in parsed.concentration_flag_ru.lower()
    assert "technology" not in parsed.concentration_flag_ru.lower()
    assert "technology" not in parsed.concentration_flag_ru.lower()
    assert "technology" not in parsed.concentration_flag_ru.lower()

    # P&L attribution vs SPY
    assert parsed.beta is not None and parsed.beta > 0.5
    assert parsed.r_squared is not None
    assert parsed.market_driven_return is not None
    assert parsed.residual_return is not None

    # Correlation matrix square
    n = len(parsed.correlation_symbols)
    assert n >= 4
    assert len(parsed.correlation_matrix) == n
    assert all(len(row) == n for row in parsed.correlation_matrix)

    # Stress: current weights through 2020 / 2022 windows (2020 crash is in fixture)
    covid = next(s for s in parsed.stress if s.scenario_id == "covid_2020")
    assert covid.observations > 0
    assert covid.total_return is not None
    assert covid.total_return < 0
    assert covid.max_drawdown is not None and covid.max_drawdown < 0
    assert "текущие веса" in covid.methodology_ru.lower()
    assert covid.equity_curve

    bear = next(s for s in parsed.stress if s.scenario_id == "bear_2022")
    assert bear.scenario_id in STRESS_SCENARIOS


def test_simple_returns_reject_nonpositive():
    assert list(simple_returns([10.0, 11.0, 12.1])) == pytest.approx([0.1, 0.1], rel=1e-9)
    assert list(simple_returns([10.0])) == []


def test_e46_08_same_series_report_var_is_fhs_not_historical():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0004, 0.012, 60)
    start = date(2024, 1, 1)
    price = 100.0
    rows: list[tuple[str, float]] = [(start.isoformat(), price)]
    day = start
    for r in rets:
        day = day + timedelta(days=1)
        price = price * (1.0 + float(r))
        rows.append((day.isoformat(), price))
    report = build_report(
        holdings=[HoldingSpec("AAA", 10_000, "equity")],
        series_by_symbol={"AAA": rows},
        lookback_days=80,
    )
    fhs95, _, _ = fhs_var_triple(rets)
    hist95, _, _ = historical_var_es(rets)
    assert report.var_95 == pytest.approx(fhs95, rel=0, abs=1e-12)
    assert fhs95 != pytest.approx(hist95, rel=0, abs=1e-9)
    assert report.methodology["method"] == "fhs_ewma"
    engine95, _ = fhs_var_es(rets, alpha=0.05)
    assert report.var_95 == pytest.approx(engine95, rel=0, abs=1e-12)


def test_e46_08_risk_analytics_math_does_not_import_historical_var():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "services" / "portfolio" / "risk_analytics_math.py"
    text = src.read_text(encoding="utf-8")
    assert "historical_var_es" not in text
    assert "fhs_var_es" in text
    assert "fhs_var_triple" in text
