"""Typed QA chat tools (Prompt 22). Numbers come from core services only."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable

from app.services.explanations.service import filter_wording
from app.services.qa.feature_flags import is_enabled

FORBIDDEN = frozenset({"place_order", "create_order", "execute_order", "submit_order"})
_lock = Lock()
_journal: list[dict[str, Any]] = []


def reset() -> None:
    with _lock:
        _journal.clear()


def catalog() -> list[dict[str, Any]]:
    return [
        {"name": "qa_portfolio_report", "in": ["user_id", "mode"], "out": ["first_screen", "headline"], "rights": "read"},
        {"name": "qa_risk", "in": ["user_id", "mode"], "out": ["var_95", "status"], "rights": "read"},
        {"name": "qa_returns", "in": ["user_id", "mode"], "out": ["twr", "mwr"], "rights": "read"},
        {"name": "qa_k1_simple_alt", "in": ["user_id", "mode"], "out": ["alternatives"], "rights": "read", "flag": "qa_k1_benchmark"},
        {"name": "qa_factor_lens", "in": ["user_id", "mode"], "out": ["enb", "sentence"], "rights": "read", "flag": "qa_factor_lens"},
        {"name": "qa_concentration", "in": ["user_id", "mode"], "out": ["hhi"], "rights": "read"},
        {"name": "qa_stress", "in": ["user_id", "mode"], "out": ["scenarios"], "rights": "read"},
        {"name": "qa_limits", "in": ["user_id"], "out": ["data_status"], "rights": "read", "flag": "qa_personal_limits"},
        {"name": "qa_calendar", "in": ["user_id"], "out": ["data_status"], "rights": "read", "flag": "qa_calendar"},
        {"name": "qa_accounts", "in": ["user_id", "mode"], "out": ["n", "mode"], "rights": "read"},
        {"name": "qa_prepare_risk_check", "in": ["ticker"], "out": ["next"], "rights": "read"},
    ]


def journal(*, user_id: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        rows = list(_journal)
    if user_id is None:
        return rows
    return [row for row in rows if row.get("user_id") == user_id]


def invoke(*, name: str, user_id: str = "demo", mode: str = "paper", ticker: str | None = None) -> dict[str, Any]:
    if name in FORBIDDEN:
        raise PermissionError("chat_cannot_create_orders")
    known = {row["name"] for row in catalog()}
    if name not in known:
        raise KeyError(name)
    handler = _HANDLERS[name]
    payload = handler(user_id=user_id, mode=mode, ticker=ticker)
    text = str(payload)
    if filter_wording(text):
        payload = {"data_status": "нет данных", "reason": "формулировка отклонена"}
    rec = {"name": name, "user_id": user_id, "mode": mode, "at": datetime.now(timezone.utc).isoformat()}
    with _lock:
        _journal.append(rec)
    payload["tool"] = name
    payload["journal_n"] = len(_journal)
    return payload


def _report(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    from app.services.portfolio_report.service import assemble

    out = assemble(user_id=user_id, mode=mode)
    return {"first_screen": out.get("first_screen"), "headline": out.get("headline"), "as_of": out.get("as_of")}


def _risk(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    from app.services.risk_engine.service import compute_risk_for_user

    return compute_risk_for_user(user_id, mode)


def _returns(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    from app.services.returns.service import as_dict, compute_returns

    return as_dict(compute_returns(user_id=user_id, mode=mode, period="inception"))  # type: ignore[arg-type]


def _factors(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    if not is_enabled("qa_factor_lens"):
        return {"data_status": "нет данных", "reason": "нет данных"}
    from app.services.factor_lens.service import explain_portfolio

    return explain_portfolio(user_id, mode=mode)


def _k1_alts(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    if not is_enabled("qa_k1_benchmark"):
        return {"data_status": "нет данных", "reason": "нет данных"}
    from app.services.benchmark_alt.service import as_dict, compare_simple_alternatives

    return as_dict(compare_simple_alternatives(user_id=user_id, mode=mode, period="inception"))


def _conc(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    from app.services.concentration.service import analyze_portfolio

    return analyze_portfolio(user_id=user_id, mode=mode)


def _stress(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    from app.services.stress_library.service import run_portfolio

    return run_portfolio(user_id=user_id, mode=mode)


def _limits(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    if not is_enabled("qa_personal_limits"):
        return {"data_status": "нет данных", "reason": "нет данных"}
    from app.services.personal_limits.service import get_limits

    return get_limits(user_id=user_id)


def _cal(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    if not is_enabled("qa_calendar"):
        return {"data_status": "нет данных", "reason": "нет данных"}
    from app.services.instrument_calendar.service import events_for_user

    return events_for_user(user_id=user_id, mode=mode)


def _accounts(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    from app.services.portfolio_book.store import get_book

    pos = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    return {"n": len(pos), "mode": mode, "data_status": "нет данных" if not pos else "ok"}


def _prepare(*, user_id: str, mode: str, ticker: str | None = None) -> dict[str, Any]:
    symbol = (ticker or "").upper()
    return {
        "next": f"/portfolio-risk?symbol={symbol}" if symbol else "/portfolio-risk",
        "creates_order": False,
        "note": "Переход к проверке риска. Чат заявку не создаёт.",
    }


_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "qa_portfolio_report": _report,
    "qa_risk": _risk,
    "qa_returns": _returns,
    "qa_k1_simple_alt": _k1_alts,
    "qa_factor_lens": _factors,
    "qa_concentration": _conc,
    "qa_stress": _stress,
    "qa_limits": _limits,
    "qa_calendar": _cal,
    "qa_accounts": _accounts,
    "qa_prepare_risk_check": _prepare,
}
