"""Meta-tests for DiagnosticsEngine (Prompt 89)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timezone

from app.services.diagnostics.engine import DiagnosticsEngine, check_macro_indicator_invariants


def _make_df(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 300
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="D")
    close = 100 * np.cumprod(1 + rng.normal(0, 0.02, n) + 0.002)
    return pd.DataFrame(
        {
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, n),
        },
        index=dates,
    )


def test_macro_invariant_catches_fed_rate_contamination():
    findings = check_macro_indicator_invariants({"rate_cb_us": 14.25, "vix": 20.0})
    failed = [f for f in findings if not f.passed]
    assert any(f.check_id == "macro.invariant.rate_cb_us" for f in failed)


def test_diagnostics_engine_golden_suite_passes():
    engine = DiagnosticsEngine()

    def _market():
        return {f"T{i}": _make_df(i) for i in range(10)}

    report = engine.run(
        macro_indicators={"rate_cb_us": 3.75, "rate_cb": 14.25, "vix": 18.0},
        market_data_factory=_market,
    )
    assert report.ok, [f.message for f in report.failures()]


def test_diagnostics_engine_detects_injected_macro_violation():
    engine = DiagnosticsEngine()
    report = engine.run(macro_indicators={"rate_cb_us": 14.25})
    assert not report.ok
    assert any(f.check_id == "macro.invariant.rate_cb_us" for f in report.failures())


def test_diagnostics_engine_spy_brief_chat_no_duplicate_block():
    engine = DiagnosticsEngine()
    report = engine.run()
    finding = next(
        f for f in report.findings if f.check_id == "golden.92.spy_brief_no_duplicate_metrics"
    )
    assert finding.passed, finding.message
