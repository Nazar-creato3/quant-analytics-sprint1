"""Quality / value / leverage from cached FMP or SEC extras. No raw dump, no extra HTTP."""
from __future__ import annotations

from typing import Any, Mapping


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def style_scores(extras: Mapping[str, Any] | None) -> dict[str, float]:
    """Map already-fetched extras into bounded style scores in roughly [-1, 1]."""
    if not extras or float(extras.get("fund_present") or 0.0) < 0.5:
        return {"quality": 0.0, "value": 0.0, "leverage": 0.0, "present": 0.0}
    roe = float(extras.get("fmp_roe") or 0.0)
    roa = float(extras.get("fmp_roa") or 0.0)
    margin = float(extras.get("fmp_margin") or 0.0)
    quality = _clip(0.5 * _clip(roe, -1.0, 1.0) + 0.3 * _clip(roa * 2.0, -1.0, 1.0) + 0.2 * _clip(margin * 2.0, -1.0, 1.0), -1.0, 1.0)
    value = _clip(float(extras.get("fmp_pe_inv") or 0.0) * 12.0, -1.0, 1.0)
    de = float(extras.get("fmp_de") or 0.0)
    # High debt/equity → negative leverage score (safer names score higher).
    leverage = _clip(1.0 - de / 2.0, -1.0, 1.0) if de > 0 else 0.0
    return {
        "quality": round(quality, 6),
        "value": round(value, 6),
        "leverage": round(leverage, 6),
        "present": 1.0,
    }


def extras_from_statements(
    statements: list[Mapping[str, Any]],
    *,
    as_of: Any,
) -> dict[str, float]:
    """Income/ratio rows keyed by fillingDate = knowledge_time. Never use a later filing."""
    from app.services.pit.clock import as_day

    cap = as_day(as_of)
    visible: list[Mapping[str, Any]] = []
    for row in statements:
        known = as_day(
            row.get("fillingDate")
            or row.get("filingDate")
            or row.get("acceptedDate")
            or row.get("filed")
        )
        if known and cap and known <= cap:
            visible.append(row)
    if not visible:
        return {"fund_present": 0.0}
    visible.sort(key=lambda r: as_day(r.get("fillingDate") or r.get("filingDate") or r.get("acceptedDate") or r.get("filed")))
    last = visible[-1]
    ni = _f(last.get("netIncome") or last.get("net_income"))
    eq = _f(last.get("totalStockholdersEquity") or last.get("equity"))
    rev = _f(last.get("revenue"))
    assets = _f(last.get("totalAssets") or last.get("assets"))
    debt = _f(last.get("totalDebt") or last.get("debt"))
    extras = {
        "fmp_roe": (ni / eq) if ni is not None and eq else 0.0,
        "fmp_roa": (ni / assets) if ni is not None and assets else 0.0,
        "fmp_margin": (ni / rev) if ni is not None and rev else 0.0,
        "fmp_de": (debt / eq) if debt is not None and eq else 0.0,
        "fmp_pe_inv": 0.0,
        "fund_present": 1.0,
    }
    extras.update({f"style_{k}": v for k, v in style_scores(extras).items()})
    return extras


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
