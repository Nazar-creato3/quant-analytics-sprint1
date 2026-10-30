"""QA chat tool registry API (Prompt 22)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.services.chat.qa_registry import catalog, invoke, journal
from app.services.qa.session_user import require_session_identity, require_session_user_id, same_user

router = APIRouter(prefix="/qa-tools", tags=["qa-tools"])


class InvokeIn(BaseModel):
    name: str
    user_id: str = "demo"
    mode: str = "paper"
    ticker: str | None = None


_TITLES = {
    "qa_portfolio_report": "Отчёт портфеля",
    "qa_risk": "Риск",
    "qa_returns": "Доходность",
    "qa_k1_simple_alt": "Простой ориентир",
    "qa_factor_lens": "Факторы",
    "qa_concentration": "Концентрация",
    "qa_stress": "Стресс",
    "qa_limits": "Лимиты",
    "qa_calendar": "Календарь",
    "qa_accounts": "Счета",
    "qa_prepare_risk_check": "Проверить риск",
}


@router.get("")
def list_tools(_user_id: str = Depends(require_session_user_id)) -> dict:
    return {
        "tools": [{"title": _TITLES.get(t["name"], "действие")} for t in catalog()],
    }


@router.get("/journal")
def get_journal(user_id: str = Depends(require_session_user_id)) -> dict:
    return {"items": journal(user_id=user_id)}


@router.post("/invoke")
def post_invoke(body: InvokeIn, session_id: str = Depends(require_session_identity)) -> dict:
    try:
        return invoke(name=body.name, user_id=same_user(body.user_id, session_id), mode=body.mode, ticker=body.ticker)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="нет доступа") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="нет данных") from exc


@router.get("/search")
def search_actions(q: str = Query(""), _user_id: str = Depends(require_session_user_id)) -> dict:
    needle = q.lower()
    rows = [
        {"kind": "section", "label": "Отчёт", "href": "/portfolio-report"},
        {"kind": "section", "label": "Риск", "href": "/portfolio-risk"},
        {"kind": "section", "label": "Факторы", "href": "/factors"},
        {"kind": "section", "label": "Прогноз", "href": "/forecasting"},
        {"kind": "section", "label": "Конструктор стратегии", "href": "/strategy-composer"},
        {"kind": "section", "label": "Бумажные боты", "href": "/bots"},
        {"kind": "action", "label": "Проверить риск", "href": "/portfolio-risk"},
        {"kind": "section", "label": "Уведомления", "href": "/notifications"},
    ]
    rows.extend({"kind": "tool", "label": _TITLES.get(t["name"], "действие"), "href": "/chat"} for t in catalog())
    if needle:
        rows = [r for r in rows if needle in r["label"].lower()]
    return {"q": q, "items": rows}
