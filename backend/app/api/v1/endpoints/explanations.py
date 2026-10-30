"""Explanation templates API (Prompt 16)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.explanations.service import render, term
from app.services.qa.feature_flags import is_enabled

router = APIRouter(prefix="/explanations", tags=["explanations"])


@router.get("")
def get_explanation(key: str = Query("hhi"), hhi: str = Query("0.5"), n: int = Query(8)) -> dict:
    if not is_enabled("qa_explanations"):
        raise HTTPException(status_code=404, detail="explanations flag off")
    values = {
        "hhi": hhi,
        "nav_clause": "Сумма портфеля в рублях — нет данных.",
        "enb": 1,
        "n": n,
        "min_n": 8,
        "pgr_pct": 50,
        "plr_pct": 50,
        "hold_w": "1.0",
        "hold_l": "1.0",
        "var_rub": "нет данных",
        "method": "fhs",
    }
    try:
        payload = render(key, values)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload["term_hhi"] = term("HHI")
    return payload
