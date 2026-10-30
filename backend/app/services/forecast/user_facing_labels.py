"""Sanitize forecast payloads so user-visible strings never leak raw engine keys."""
from __future__ import annotations

from typing import Any

FORECAST_DISCLAIMER_RU = (
    "Прогноз носит вероятностный характер и не является инвестиционной рекомендацией. "
    "Прошлые результаты не гарантируют будущую доходность."
)

_TECHNICAL_MARKERS = (
    "chronos",
    "lgbm",
    "lightgbm",
    "bocpd",
    "stacking",
    "shap",
    "regime_match",
    "calibration_error",
)


def looks_technical(text: str) -> bool:
    lower = (text or "").lower()
    return any(m in lower for m in _TECHNICAL_MARKERS) or ("_" in lower and lower.isascii())


def _needs_canonical_disclaimer(current: str) -> bool:
    if not current or looks_technical(current) or len(current) > 180:
        return True
    lower = current.lower()
    return "инвестицион" not in lower or "вероятност" not in lower


def attach_display_labels(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with disclaimer_ru normalized when needed."""
    out = dict(payload)
    tr = out.get("track_record")
    if isinstance(tr, dict):
        tr = dict(tr)
        current = str(tr.get("disclaimer_ru") or "").strip()
        if _needs_canonical_disclaimer(current):
            tr["disclaimer_ru"] = FORECAST_DISCLAIMER_RU
        out["track_record"] = tr
    disc = out.get("disclaimer_ru")
    if isinstance(disc, str) and _needs_canonical_disclaimer(disc):
        out["disclaimer_ru"] = FORECAST_DISCLAIMER_RU
    return out
