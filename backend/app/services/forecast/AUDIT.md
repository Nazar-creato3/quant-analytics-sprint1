# Terminal Forecast Numeric Integrity — Root-Cause Audit

Audit date: 2026-08-05. Repro fixture: GOOGL (applies to all tickers).

## Bug 1 — Zeroed-out risk metrics

**Symptom:** Volatility Expansion Probability, Liquidity Risk Score, Event Impact Score,
Correlation Shift Score, Interval P10 render as 0%/blank.

**Root cause:** `PredictionHierarchyOrchestrator.get_forecast()` called
`ForecastEngine.compute_from_inputs()` with a bare `ForecastInputBundle` (prices + regime only).
Correlation weights, event-impact score, and liquidity features were never loaded — those paths
exist only on `ForecastEngine.forecast_instrument()`. Missing inputs silently default to 0.0.

**Fix:** Enrich the bundle via the same loaders as `forecast_instrument()` before composition.
Frontend: treat bare 0 with no backing field as `insufficient_data`, not a computed zero.

## Bug 2 — Identical rolling accuracy (50.0%) across windows

**Symptom:** All six evaluation windows show identical 50.0% accuracy despite differing MAE.

**Root cause:** `build_track_record_chart_data()` reused a single headline accuracy from
`report.level_accuracy` and the global `report.calibration_error` for every window label.

**Fix:** Compute per-window directional accuracy and MAE from trailing slices of validation
pairs (`forecast_matches`, `confidences`, `outcomes`) inside `HierarchyValidationEngine`.

## Bug 3 — SPY vs ^GSPC near-zero correlation

**Symptom:** ETF and tracked index show ~0 correlation instead of ~0.99+.

**Root cause:** `_compute_correlation_matrix()` aligned return *tails* by length, not by calendar
date. SPY and ^GSPC loaded independently could have different bar counts / stale tails, so the
last N returns referred to different trading days.

**Fix:** Join on OHLCV timestamps; align returns on shared dates only. Regression test asserts
corr(SPY, ^GSPC) > 0.95 on synthetic co-moving series.

## Bug 4 — Regime Map contradiction (SPY sideways vs ^GSPC high-vol)

**Symptom:** Functionally identical instruments get incompatible regime labels; 100% confidence.

**Root cause:** Each symbol classified independently on misaligned price series. HMM confidence
could saturate when entropy → 0 (no upper soft-cap).

**Fix:** For ETF/index alias pairs, classify once on date-aligned returns and mirror the entry.
Cap HMM confidence at 0.95.

## Bug 5 — Direction / signal / interval inconsistency

**Symptom:** Directional point forecast with weak signal but symmetric P10/P90 interval.

**Root cause:** Point forecast from momentum, interval from symmetric vol band (`±vol * 1.645`)
in separate code paths (`_build_point_forecast` vs `_build_interval_forecast`).

**Fix:** `build_forecast_distribution()` derives point, signal strength, and quantiles from one
vol + momentum model; interval skew follows signal sign/strength.
