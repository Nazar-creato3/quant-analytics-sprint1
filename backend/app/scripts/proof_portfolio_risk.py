"""Proof: institutional risk pack on a real multi-name test book (no UI)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np

from app.services.portfolio.risk_analytics_math import HoldingSpec, build_report


def _book_series() -> dict[str, list[tuple[str, float]]]:
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


def main() -> None:
    holdings = [
        HoldingSpec("AAPL", 40_000, "technology"),
        HoldingSpec("MSFT", 30_000, "technology"),
        HoldingSpec("NVDA", 20_000, "technology"),
        HoldingSpec("QQQ", 10_000, "indices"),
    ]
    report = build_report(holdings=holdings, series_by_symbol=_book_series(), benchmark_symbol="SPY")
    proof = {
        "portfolio": {
            "holdings": [h.symbol for h in holdings],
            "var_95": report.var_95,
            "var_99": report.var_99,
            "var_95_usd": report.var_95_usd,
            "lookback": [report.lookback_start, report.lookback_end],
            "method": report.methodology.get("method"),
            "method_ru": report.methodology.get("method_ru"),
            "beta": report.beta,
            "alpha": report.alpha,
            "r_squared": report.r_squared,
            "avg_pairwise_correlation": report.avg_pairwise_correlation,
            "concentration_flag_ru": report.concentration_flag_ru,
            "covid_2020_return": next(
                (s.total_return for s in report.stress if s.scenario_id == "covid_2020"), None
            ),
            "covid_2020_max_drawdown": next(
                (s.max_drawdown for s in report.stress if s.scenario_id == "covid_2020"), None
            ),
        }
    }
    print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
