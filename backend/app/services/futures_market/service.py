"""Futures market description from fixtures (prompt 58B). Live ISS/T-Invest behind later collector."""
from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

from app.services.explanations.service import filter_wording
from app.services.futures_market.math import volume_profile
from app.services.qa.feature_flags import is_enabled

DATA = Path(__file__).resolve().parents[4] / "backend" / "data" / "futures_market"


def _yaml_rows(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    out: dict[str, Any] = {"rows": []}
    current: dict[str, Any] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("source:"):
            out["source"] = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("positive_pays:"):
            out["positive_pays"] = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("limit:"):
            out["limit"] = float(line.split(":", 1)[1].strip())
        elif line.startswith("ticker:") and current is None and "rows:" not in line:
            out["ticker"] = line.split(":", 1)[1].strip()
        elif line.startswith("- "):
            if current:
                out["rows"].append(current)
            current = {}
            rest = line[2:]
            if ":" in rest:
                k, v = rest.split(":", 1)
                current[k.strip()] = _scalar(v.strip())
        elif current is not None and ":" in line:
            k, v = line.split(":", 1)
            current[k.strip()] = _scalar(v.strip())
    if current:
        out["rows"].append(current)
    return out


def _scalar(v: str) -> Any:
    v = v.strip().strip('"')
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def _skew_percentile(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    skews = []
    for r in rows:
        phys = float(r.get("phys_long") or 0) - float(r.get("phys_short") or 0)
        skews.append(phys)
    last = skews[-1]
    ordered = sorted(skews)
    rank = sum(1 for x in ordered if x <= last)
    return round(100.0 * rank / len(ordered), 1)


def explain_market(ticker: str = "MIX", *, user_token: bool = False) -> dict[str, Any]:
    started = perf_counter()
    caption = "описание рынка: что есть на графике, не направление"
    if filter_wording(caption):
        caption = "нет данных"
    if not is_enabled("qa_futures_market"):
        return {"data_status": "нет данных", "reason": "нет данных"}
    trades_path = DATA / "trades_mix_fixture.json"
    trades = json.loads(trades_path.read_text(encoding="utf-8")) if trades_path.is_file() else []
    profile = volume_profile(trades, tick=1.0)
    futoi = _yaml_rows(DATA / "futoi.yaml")
    funding = _yaml_rows(DATA / "funding.yaml")
    book = _yaml_rows(DATA / "orderbook.yaml")
    mean_q = float(book.get("mean_level_qty") or 10)
    densities = []
    if user_token:
        densities = [r for r in book.get("rows") or [] if float(r.get("qty") or 0) > 5 * mean_q]
    meetings = Path(__file__).resolve().parents[4] / "data" / "cbr" / "meetings.yaml"
    calendar = []
    if meetings.is_file():
        for line in meetings.read_text(encoding="utf-8").splitlines():
            if "date:" in line:
                calendar.append({"type": "cbr_meeting", "date": line.split(":", 1)[1].strip().strip('"')})
    rows = futoi.get("rows") or []
    last = rows[-1] if rows else {}
    prev = rows[-2] if len(rows) > 1 else {}
    week = rows[0] if rows else {}
    return {
        "data_status": "ok" if trades else "нет данных",
        "ticker": ticker.upper(),
        "caption": caption,
        "profile": profile,
        "futoi": {
            "source": futoi.get("source"),
            "as_of": last.get("date"),
            "phys_long": last.get("phys_long"),
            "phys_short": last.get("phys_short"),
            "legal_long": last.get("legal_long"),
            "legal_short": last.get("legal_short"),
            "phys_count": last.get("phys_count"),
            "legal_count": last.get("legal_count"),
            "day_change_phys_long": None
            if last.get("phys_long") is None or prev.get("phys_long") is None
            else last["phys_long"] - prev["phys_long"],
            "week_change_phys_long": None
            if last.get("phys_long") is None or week.get("phys_long") is None
            else last["phys_long"] - week["phys_long"],
            "skew_percentile": _skew_percentile(rows),
            "history": rows,
        },
        "oi_volume": {"open_interest": None, "volume": profile.get("total_volume"), "note": "OI нет в фикстуре сделок"},
        "funding": {
            "positive_pays": funding.get("positive_pays") or "положительный фандинг платят длинные позиции коротким",
            "limit": funding.get("limit"),
            "history": funding.get("rows") or [],
        },
        "orderbook_densities": densities,
        "orderbook_note": None if user_token else "стакан только по токену самого пользователя",
        "calendar": calendar[:8],
        "methodology": "/methodology/futures-market",
        "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
    }
