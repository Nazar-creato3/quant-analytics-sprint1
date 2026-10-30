"""Platt-lite + ECE. No paid tracker. Bad ECE → score 5, size 0."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence

from app.services.ml.model import MODEL_DIR


def _ece_path() -> Path:
    return MODEL_DIR / "forecast_ece.json"


def expected_calibration_error(
    probs: Sequence[float],
    outcomes: Sequence[int],
    *,
    n_bins: int = 10,
) -> dict[str, float]:
    """Binary ECE. outcomes are 0/1. Honest empty if n < 20."""
    pairs = [
        (min(1.0, max(0.0, float(p))), 1 if int(y) else 0)
        for p, y in zip(probs, outcomes)
    ]
    n = len(pairs)
    if n < 20:
        return {"n": 0, "ece": 0.0, "reliable": True}
    bins = [[] for _ in range(n_bins)]
    for p, y in pairs:
        idx = min(n_bins - 1, int(p * n_bins))
        bins[idx].append((p, y))
    ece = 0.0
    for bucket in bins:
        if not bucket:
            continue
        conf = sum(p for p, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(acc - conf)
    return {"n": float(n), "ece": round(ece, 6), "reliable": ece <= 0.12}


def platt_apply(p: float, *, a: float = 1.0, b: float = 0.0) -> float:
    """Logistic on logit(p). Identity when a=1,b=0."""
    raw = min(1.0 - 1e-6, max(1e-6, float(p)))
    logit = math.log(raw / (1.0 - raw))
    z = a * logit + b
    if z >= 30:
        return 1.0
    if z <= -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def fit_platt(probs: Sequence[float], outcomes: Sequence[int]) -> tuple[float, float]:
    """One-step logistic on logit(p). Falls back to identity if thin."""
    xs: list[float] = []
    ys: list[float] = []
    for p, y in zip(probs, outcomes):
        raw = min(1.0 - 1e-6, max(1e-6, float(p)))
        xs.append(math.log(raw / (1.0 - raw)))
        ys.append(1.0 if int(y) else 0.0)
    if len(xs) < 20:
        return 1.0, 0.0
    # Newton on intercept+slope for Bernoulli.
    a, b = 1.0, 0.0
    for _ in range(12):
        g_a = g_b = h_aa = h_bb = h_ab = 0.0
        for x, y in zip(xs, ys):
            z = a * x + b
            p_hat = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            w = p_hat * (1.0 - p_hat)
            err = p_hat - y
            g_a += err * x
            g_b += err
            h_aa += w * x * x
            h_bb += w
            h_ab += w * x
        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-12:
            break
        a -= (h_bb * g_a - h_ab * g_b) / det
        b -= (h_aa * g_b - h_ab * g_a) / det
    return float(a), float(b)


def kelly_mult(p_cal: float, *, payoff: float = 1.0, cap: float = 0.25) -> float:
    """Fractional Kelly as size multiplier ≤ 1. Edge≤0 → 0."""
    p = min(1.0, max(0.0, float(p_cal)))
    b = max(float(payoff), 1e-6)
    f = (p * (b + 1.0) - 1.0) / b
    if f <= 0:
        return 0.0
    return min(1.0, f / cap) if cap > 0 else 0.0


def persist_ece(report: dict[str, Any]) -> None:
    try:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        _ece_path().write_text(json.dumps(report), encoding="utf-8")
    except OSError:
        return


def load_ece() -> dict[str, Any]:
    try:
        return json.loads(_ece_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"n": 0, "ece": 0.0, "reliable": True}


def score_1_10(p_beat: float, *, ece_report: dict[str, Any] | None = None) -> tuple[int, bool]:
    """Rounded P×10, or 5 if ECE is broken. Second flag = score is trusted."""
    report = ece_report if ece_report is not None else load_ece()
    if float(report.get("n") or 0) >= 40 and not report.get("reliable", True):
        return 5, False
    clipped = min(1.0, max(0.0, float(p_beat)))
    return max(1, min(10, int(round(clipped * 10.0)) or 1)), True


def ece_from_track_payloads(payloads: Sequence[dict[str, Any]], *, horizon: int = 20) -> dict[str, Any]:
    probs: list[float] = []
    ys: list[int] = []
    key_p = "p_beat_20" if horizon == 20 else "p_beat_60"
    key_ex = "excess_20" if horizon == 20 else "excess_60"
    for payload in payloads:
        beat = (payload or {}).get("market_beat") or {}
        track = (payload or {}).get("excess_track") or {}
        p = beat.get(key_p)
        ex = track.get(key_ex)
        if p is None or ex is None:
            continue
        probs.append(float(p))
        ys.append(1 if float(ex) > 0 else 0)
    report = expected_calibration_error(probs, ys)
    if report["n"] >= 20:
        a, b = fit_platt(probs, ys)
        report["platt_a"] = round(a, 6)
        report["platt_b"] = round(b, 6)
    persist_ece(report)
    return report
