"""QuantStats metrics from the same daily portfolio returns as GET /risk."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Sequence

import numpy as np
import pandas as pd


def fund_metrics(
    daily_returns: Sequence[float],
    *,
    attribution: dict[str, Any] | None = None,
    dates: Sequence[str] | None = None,
) -> dict[str, Any]:
    """CAGR, max drawdown, Sharpe, monthly map. Numbers from code, not copy.

    Methodology: docs/methodology/risk.md (K6). Returns are the weighted
    portfolio series already used by ``compute_risk_for_user``.

    Calendar months are filled only when ``dates`` are provided for each
    return. Without dates we do not attribute the series to the last N
    business days ending today.
    """
    r = [float(x) for x in daily_returns]
    out: dict[str, Any] = {
        "source": "fund_report.quantstats",
        "n": len(r),
        "cagr": None,
        "max_dd": None,
        "sharpe": None,
        "monthly": [],
        "data_status": "нет данных" if len(r) < 2 else "ok",
        "k1": {
            "status": "pending",
            "data_status": "нет данных",
            "reason": None,
            "alternatives": [],
        },
        "attribution": {
            "enb": (attribution or {}).get("enb"),
            "components": (attribution or {}).get("components") or [],
            "data_status": (attribution or {}).get("data_status") or "нет данных",
        },
        "engine": "sklearn.LedoitWolf+quantstats",
        "as_of": datetime.now(UTC).date().isoformat(),
    }
    if len(r) < 2:
        return out
    wealth = np.cumprod(1.0 + np.asarray(r, dtype=float))
    peak = np.maximum.accumulate(wealth)
    dd = wealth / np.clip(peak, 1e-12, None) - 1.0
    years = len(r) / 252.0
    cagr = float(wealth[-1] ** (1.0 / years) - 1.0) if years > 0 and wealth[-1] > 0 else None
    vol = float(np.std(r, ddof=1)) if len(r) > 1 else 0.0
    sharpe = float(np.mean(r) / vol * np.sqrt(252.0)) if vol > 1e-18 else None
    out["cagr"] = None if cagr is None else round(cagr, 6)
    out["max_dd"] = round(float(dd.min()), 6)
    out["sharpe"] = None if sharpe is None else round(sharpe, 4)

    calendar = _calendar_index(r, dates)
    if calendar is None:
        out["monthly"] = []
        out["quantstats"] = False
        out["monthly_status"] = "нет дат ряда"
        return out

    series = pd.Series(r, index=calendar, dtype=float)
    try:
        import quantstats as qs

        out["cagr"] = round(float(qs.stats.cagr(series)), 6)
        out["max_dd"] = round(float(qs.stats.max_drawdown(series)), 6)
        out["sharpe"] = round(float(qs.stats.sharpe(series)), 4)
        monthly = qs.stats.monthly_returns(series)
        out["monthly"] = _monthly_rows(monthly)
        out["quantstats"] = True
    except Exception:
        out["quantstats"] = False
        out["monthly"] = _monthly_from_series(series)
    return out


def _calendar_index(returns: list[float], dates: Sequence[str] | None) -> pd.DatetimeIndex | None:
    if dates is None:
        return None
    if len(dates) != len(returns):
        return None
    try:
        idx = pd.to_datetime(list(dates), utc=True)
    except (TypeError, ValueError):
        return None
    if bool(pd.isna(idx).any()):
        return None
    return pd.DatetimeIndex(idx)


def _monthly_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if frame is None or frame.empty:
        return rows
    month_cols = [c for c in frame.columns if str(c) not in {"EOY", "eoy"}]
    for year, row in frame.iterrows():
        for col in month_cols:
            val = row[col]
            if pd.isna(val):
                continue
            rows.append({"year": int(year), "month": str(col), "return": round(float(val), 6)})
    return rows


def _monthly_from_series(series: pd.Series) -> list[dict[str, Any]]:
    m = series.resample("ME").apply(lambda x: float(np.prod(1.0 + x) - 1.0))
    rows: list[dict[str, Any]] = []
    for ts, val in m.items():
        rows.append({"year": int(ts.year), "month": f"{int(ts.month):02d}", "return": round(float(val), 6)})
    return rows
