"""Registry status, validation report, champion/challenger (Prompt 11B)."""
from __future__ import annotations

from typing import Any

from app.services.forecast_log.summary import internal_summary
from app.services.model_risk.math import (
    binomial_p_beats_half,
    brier,
    conformal_interval,
    coverage,
    detect_lookahead,
    diebold_mariano,
    naive_constant,
    naive_persist,
    psi,
    purged_walk_forward,
)
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.series import get_series

CARD = "docs/models/forecast_core.heuristic.v1.md"
CHALLENGER = "forecast_core.persist.v0"
_SHADOW: list[dict[str, Any]] = []


def _empty_report() -> dict[str, Any]:
    return {
        "model_id": "forecast_core.heuristic.v1",
        "card": CARD,
        "lookahead_injected_detected": False,
        "lookahead_clean": True,
        "walk_forward_hits": 0,
        "walk_forward_n": 0,
        "binomial_p": None,
        "beats_naive": False,
        "diebold_mariano_vs_persist": None,
        "brier": None,
        "conformal_coverage": None,
        "psi_self": None,
        "status": "нет данных",
        "note": "нет данных",
        "naive_constant_up": [],
        "data_status": "нет данных",
    }


def validate_heuristic(returns: list[float] | None = None) -> dict[str, Any]:
    series = list(returns) if returns is not None else list(get_series("SBER") or [])
    if len(series) < 12:
        return _empty_report()
    leaky_feat = series[1:] + [0.0]
    leak = detect_lookahead(leaky_feat, series)
    leak_clean = detect_lookahead(series, series)
    # lagged feature should leak; contemporaneous less so against next-next
    preds = purged_walk_forward(series, embargo=1)
    signs = [1 if x > 0 else (-1 if x < 0 else 0) for x in series[6 : 6 + len(preds)]]
    hits = sum(1 for a, b in zip(preds, signs) if a == b and a != 0)
    n = sum(1 for a in preds if a != 0)
    persist = naive_persist(series)
    _always_up = naive_constant(len(series), 1)
    err_m = [0.0 if a == b else 1.0 for a, b in zip(preds, signs)]
    err_n = [0.0 if persist[i] == signs[i] else 1.0 for i in range(min(len(persist), len(signs)))]
    probs = [0.55 if p > 0 else 0.45 for p in preds]
    lows, highs = [], []
    for i, p in enumerate(preds):
        lo, hi = conformal_interval([s - 0.0 for s in series[: i + 5]], float(p), 0.1)
        lows.append(lo)
        highs.append(hi)
    report = {
        "model_id": "forecast_core.heuristic.v1",
        "card": CARD,
        "lookahead_injected_detected": leak,
        "lookahead_clean": leak_clean,
        "walk_forward_hits": hits,
        "walk_forward_n": n,
        "binomial_p": binomial_p_beats_half(hits, max(n, 1)),
        "beats_naive": False,
        "diebold_mariano_vs_persist": diebold_mariano(err_m, err_n) if err_n else 0.0,
        "brier": brier(probs, signs[: len(probs)]),
        "conformal_coverage": coverage([float(s) for s in signs[: len(lows)]], lows, highs),
        "psi_self": psi(series[: len(series) // 2], series[len(series) // 2 :]),
        "status": "beta",
        "note": "на коротком горизонте превосходство над наивной не заявлено",
        "naive_constant_up": _always_up[:3],
    }
    report["beats_naive"] = report["binomial_p"] < 0.05 and hits / max(n, 1) > 0.5
    if report["beats_naive"]:
        report["status"] = "ready"
    return report


def shadow_challenger(ticker: str, champion_dir: int, persist_dir: int) -> None:
    _SHADOW.append({"ticker": ticker, "champion": champion_dir, "challenger": persist_dir, "model": CHALLENGER})


def maybe_promote() -> bool:
    """Replace champion only with statistical rule (n>=30 and challenger better). Not auto-on."""
    if len(_SHADOW) < 30:
        return False
    better = sum(1 for r in _SHADOW if r["challenger"] != 0 and r["challenger"] != r["champion"])
    return binomial_p_beats_half(better, len(_SHADOW)) < 0.01


def status() -> dict[str, Any]:
    if not is_enabled("qa_model_risk"):
        raise RuntimeError("qa_model_risk off")
    journal = internal_summary()
    report = validate_heuristic()
    drift = report.get("psi_self")
    reason = None
    if report.get("brier") is None:
        reason = "нет данных"
    elif drift is not None and drift > 0.25:
        report["status"] = "beta"
        reason = "ряд изменился сильнее обычного"
    return {
        "registry": [
            {
                "model_id": "forecast_core.heuristic.v1",
                "card": CARD,
                "role": "champion",
                "available": True,
                "weight": 1.0,
                "weight_source": "единственный доступный компонент",
            },
            {
                "model_id": "stacking",
                "role": "component",
                "available": False,
                "weight": 0.0,
                "weight_source": "нет файла модели",
            },
            {
                "model_id": "lob",
                "role": "component",
                "available": False,
                "weight": 0.0,
                "weight_source": "нет стакана",
            },
            {
                "model_id": CHALLENGER,
                "role": "challenger",
                "available": True,
                "weight": 0.0,
                "weight_source": "тень, без авто-замены",
            },
        ],
        "validation": report,
        "journal": journal,
        "challenger_shadow": len(_SHADOW),
        "promote": maybe_promote(),
        "user_reason": reason or report["note"],
        "calibrated_note": "нет данных" if report.get("brier") is None else "оценка по вашему ряду",
    }
