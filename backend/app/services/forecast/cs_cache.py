"""Latest cross-section ranks for inference (written on panel retrain / ranks)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.ml.model import MODEL_DIR


def _cs_path() -> Path:
    return MODEL_DIR / "forecast_cs_latest.json"


def load_cs_features(symbol: str) -> dict[str, float]:
    try:
        raw = json.loads(_cs_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    row = raw.get((symbol or "").strip().upper()) or raw.get("_market") or {}
    return {
        "cs_ret5_rank": float(row.get("cs_ret5_rank") or 0.0),
        "cs_ret21_rank": float(row.get("cs_ret21_rank") or 0.0),
        "cs_breadth": float(row.get("cs_breadth") or 0.0),
    }


def save_cs_features(by_symbol: dict[str, dict[str, Any]]) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    _cs_path().write_text(json.dumps(by_symbol, ensure_ascii=False), encoding="utf-8")


def ranks_from_returns(ret_map: dict[str, float]) -> dict[str, dict[str, float]]:
    """Percentile rank in (0,1]; breadth = share of names with ret > 0."""
    items = [(k, v) for k, v in ret_map.items() if v is not None]
    if not items:
        return {}
    vals = [v for _, v in items]
    n = len(vals)
    breadth = sum(1 for v in vals if v > 0) / n
    ordered = sorted(items, key=lambda p: p[1])
    out: dict[str, dict[str, float]] = {}
    for i, (sym, _) in enumerate(ordered):
        out[sym] = {"rank": (i + 1) / n, "breadth": breadth}
    return out
