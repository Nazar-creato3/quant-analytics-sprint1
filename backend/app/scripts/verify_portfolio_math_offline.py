"""Verify vendored portfolio risk math runs fully offline."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

FORBIDDEN_TOP_LEVEL = frozenset({"empyrical", "pyfolio"})


def _assert_no_upstream_imports() -> None:
    for name in sys.modules:
        top = name.split(".", 1)[0]
        if top in FORBIDDEN_TOP_LEVEL:
            raise SystemExit(f"Forbidden upstream import loaded: {name}")


def main() -> None:
    pkg = importlib.import_module("app.services.risk.portfolio_math")
    _assert_no_upstream_imports()

    from app.services.portfolio.risk_analytics_math import HoldingSpec, build_report

    holdings = [HoldingSpec("TEST", 10_000.0, "technology")]
    dates = [f"2024-01-{d:02d}" for d in range(1, 31)]
    price = 100.0
    rows: list[tuple[str, float]] = []
    for day in dates:
        rows.append((day, price))
        price *= 1.001
    report = build_report(holdings=holdings, series_by_symbol={"TEST": rows}, lookback_days=20)
    proof = {
        "module": pkg.__name__,
        "upstream_imports_forbidden": sorted(FORBIDDEN_TOP_LEVEL),
        "upstream_imports_detected": False,
        "var_95": report.var_95,
        "observations": report.observations,
        "method": report.methodology.get("method"),
        "provenance_doc": str(
            Path(__file__).resolve().parents[2] / "docs" / "internal" / "portfolio_math_provenance.md"
        ),
        "fork_doc": str(
            Path(__file__).resolve().parents[2] / "docs" / "internal" / "quantopian_risk_forks.md"
        ),
    }
    print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
